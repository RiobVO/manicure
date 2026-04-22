"""
Команда /status — ops-диагностика для владельца салона и автора.

Показывает: tenant_slug, uptime, размер БД, время последнего локального бэкапа,
статус Redis (ping), последняя увиденная ошибка. Всё — по /status-команде,
только для админов.

Также команда /backup_now — ручной бэкап (локально + в BACKUP_CHAT_ID если задан).
"""
import glob
import html
import logging
import os
from datetime import datetime

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

from config import BACKUP_CHAT_ID, DB_PATH, REDIS_URL, TENANT_SLUG
from db.connection import backup_db, get_db
from utils.admin import is_admin
from utils.error_reporter import get_last_error, get_start_time
from utils.timezone import get_tz, now_local

logger = logging.getLogger(__name__)

router = Router(name="admin_status")


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return

    lines: list[str] = ["<b>🛠 Status</b>", f"Салон: <code>{TENANT_SLUG}</code>"]

    start = get_start_time()
    if start is not None:
        delta = now_local() - start
        total_seconds = int(delta.total_seconds())
        h, rem = divmod(total_seconds, 3600)
        m, s = divmod(rem, 60)
        lines.append(f"Uptime: {h}ч {m}м {s}с")

    # размер БД
    try:
        size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
        lines.append(f"БД: {size_mb:.2f} MB ({DB_PATH})")
    except OSError as exc:
        lines.append(f"БД: ошибка чтения ({exc})")

    # последний локальный бэкап
    try:
        backups = sorted(glob.glob("backups/manicure_backup_*.db"))
        if backups:
            # tz=get_tz() обязателен: системная TZ в docker = UTC, остальные строки в /status — tenant TZ.
            mtime = datetime.fromtimestamp(os.path.getmtime(backups[-1]), tz=get_tz())
            lines.append(
                f"Бэкап: {mtime.strftime('%Y-%m-%d %H:%M')} ({len(backups)} файлов)"
            )
        else:
            lines.append("Бэкапов ещё нет (запустится через 6ч или вручную)")
    except Exception as exc:
        lines.append(f"Бэкапы: ошибка чтения — {exc}")

    # Redis ping
    if REDIS_URL:
        try:
            from redis.asyncio import Redis

            client = Redis.from_url(REDIS_URL)
            await client.ping()
            await client.aclose()
            lines.append("Redis: ✅")
        except Exception as exc:
            lines.append(f"Redis: ❌ {type(exc).__name__}: {exc}")
    else:
        lines.append("Redis: — (MemoryStorage)")

    # последняя ошибка
    last_err = get_last_error()
    if last_err:
        at = last_err["at"].strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"\n⚠ Последняя ошибка {at}:")
        # HTML-escape: exception.msg / context приходят из пользовательского текста
        # (callback data, сообщения), могут содержать < > & → BadRequest без escape.
        err_type = html.escape(last_err["type"])
        err_msg = html.escape(last_err["msg"][:200])
        lines.append(f"<code>{err_type}: {err_msg}</code>")
        if last_err.get("context"):
            lines.append(f"ctx: <code>{html.escape(last_err['context'])}</code>")
    else:
        lines.append("\n✅ Ошибок с запуска: 0")

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("backup_now"))
async def cmd_backup_now(message: Message) -> None:
    """
    Ручной бэкап: локальная копия + (опционально) отправка в BACKUP_CHAT_ID.
    Полезно перед рискованным действием (правка часов, удаление услуги).
    """
    if not message.from_user or not is_admin(message.from_user.id):
        return

    status_msg = await message.answer("📦 Делаю бэкап…")

    try:
        path = await backup_db()
    except Exception:
        logger.exception("Ручной бэкап упал")
        try:
            await status_msg.edit_text("❌ Ошибка при создании бэкапа. Смотри логи.")
        except Exception:
            pass
        return

    if not path:
        try:
            await status_msg.edit_text("❌ Не удалось создать бэкап. Смотри логи.")
        except Exception:
            pass
        return

    size_mb = os.path.getsize(path) / (1024 * 1024)
    filename = os.path.basename(path)

    # Отправка в TG-канал — необязательная часть. Провал не трогает локальную копию.
    tg_status = ""
    if BACKUP_CHAT_ID is not None:
        try:
            timestamp = now_local().strftime("%Y-%m-%d %H:%M")
            caption = f"[{TENANT_SLUG}] manual backup {timestamp} • {size_mb:.1f} MB"
            await message.bot.send_document(
                chat_id=BACKUP_CHAT_ID,
                document=FSInputFile(path),
                caption=caption,
            )
            tg_status = "\n☁ Отправлен в канал."
        except Exception:
            logger.warning("Не удалось отправить ручной бэкап в TG", exc_info=True)
            tg_status = "\n⚠ В канал не отправлен (смотри логи)."

    try:
        await status_msg.edit_text(
            f"✅ Бэкап: <code>{html.escape(filename)}</code> · {size_mb:.1f} MB"
            f"{tg_status}",
            parse_mode="HTML",
        )
    except Exception:
        pass


async def _force_send_reminder(
    message: Message, reminder_type: str, kind_label: str
) -> None:
    """
    Принудительно шлёт 24h/2h напоминание на ближайшую scheduled-запись
    самого админа (который отправил команду). Игнорирует окно и dedup —
    нужно для smoke-теста UI напоминания без ожидания 2 часа.

    Снимает запись из sent_reminders перед отправкой, чтобы повторные
    вызовы работали.
    """
    if not message.from_user or not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id
    db = await get_db()
    # Ищем ближайшую scheduled-запись этого tg-пользователя.
    cursor = await db.execute(
        """SELECT id, service_name, time FROM appointments
           WHERE user_id = ? AND status = 'scheduled'
           ORDER BY date ASC, time ASC
           LIMIT 1""",
        (user_id,),
    )
    row = await cursor.fetchone()
    if not row:
        await message.answer(
            "⚠ У тебя нет scheduled-записей. Сделай одну через /start → "
            "«Записаться», потом запусти команду снова."
        )
        return
    appt_id, service_name, time = row

    # Сбрасываем dedup, чтобы повторные /test_reminder_* работали подряд.
    await db.execute(
        "DELETE FROM sent_reminders WHERE appointment_id = ? AND reminder_type = ?",
        (appt_id, reminder_type),
    )
    await db.commit()

    from scheduler import _send_24h_reminder, _send_2h_reminder
    sender = _send_24h_reminder if reminder_type == "reminder_24h" else _send_2h_reminder
    await sender(message.bot, user_id, service_name, time, appt_id)

    await message.answer(
        f"✅ Отправил <b>{kind_label}</b> напоминание для записи #{appt_id}\n"
        f"Услуга: {html.escape(service_name)} · время: {time}\n\n"
        f"Проверь что выше пришло в этот чат.",
        parse_mode="HTML",
    )


@router.message(Command("test_reminder_24h"))
async def cmd_test_reminder_24h(message: Message) -> None:
    """Шлёт 24h напоминание немедленно — для smoke-теста."""
    await _force_send_reminder(message, "reminder_24h", "24-часовое")


@router.message(Command("test_reminder_2h"))
async def cmd_test_reminder_2h(message: Message) -> None:
    """Шлёт 2h напоминание немедленно — для smoke-теста."""
    await _force_send_reminder(message, "reminder_2h", "2-часовое")
