"""
Планировщик напоминаний с дедупликацией.

Типы напоминаний:
  • reminder_24h  — за 20-28 часов до визита
  • reminder_2h   — за 1.5-2.5 часа до визита

Окна и интервал опроса — в constants.py.
"""
import logging
import os
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BACKUP_CHAT_ID, DB_PATH, ERROR_CHAT_ID, LICENSE_CONTACT, TENANT_SLUG
from constants import (
    REMINDER_2H_MAX,
    REMINDER_2H_MIN,
    REMINDER_24H_MAX,
    REMINDER_24H_MIN,
    REMINDER_POLL_INTERVAL_MIN,
)
from utils.timezone import now_local, get_tz
from utils.error_reporter import report_error
from utils.heartbeat import send_heartbeat
from utils.license import LicenseState
from utils.ui import h
from db import (
    get_upcoming_appointments,
    mark_reminder_sent,
    was_reminder_sent,
)
from db.connection import backup_db, get_db

logger = logging.getLogger(__name__)


# ─── Retention ────────────────────────────────────────────────────────────────
# Срок хранения «болтающихся» строк:
#   admin_logs      — audit-history, 180 дней достаточно для разбора споров
#   sent_reminders  — дедуп-маркеры, нужны только на горизонт будущих записей;
#                     90 дней с запасом (самая дальняя запись обычно ≤ 14 дней)
ADMIN_LOGS_RETENTION_DAYS = 180
SENT_REMINDERS_RETENTION_DAYS = 90


async def _prune_old_rows() -> None:
    """
    Удаляет устаревшие строки из admin_logs и sent_reminders.
    Без этого через год у активной админши ~50k строк в admin_logs → бэкапы
    пухнут, send_document в TG упирается в лимит 50 МБ.

    Атомарно под write_lock + BEGIN IMMEDIATE — симметрично с остальными
    write-путями (db/appointments.py, db/payments.py). Без этого параллельный
    commit из другого хендлера флашил наши DELETE частично.
    """
    from db.connection import get_write_lock
    db = await get_db()
    lock = await get_write_lock()
    async with lock:
        await db.execute("BEGIN IMMEDIATE")
        try:
            cur = await db.execute(
                "DELETE FROM admin_logs WHERE created_at < date('now', ?)",
                (f"-{ADMIN_LOGS_RETENTION_DAYS} days",),
            )
            admin_removed = cur.rowcount
            cur = await db.execute(
                "DELETE FROM sent_reminders WHERE sent_at < date('now', ?)",
                (f"-{SENT_REMINDERS_RETENTION_DAYS} days",),
            )
            reminders_removed = cur.rowcount
            await db.execute("COMMIT")
        except Exception:
            await db.execute("ROLLBACK")
            raise
    if admin_removed or reminders_removed:
        logger.info(
            "retention: admin_logs=-%d, sent_reminders=-%d",
            admin_removed, reminders_removed,
        )


async def send_reminders(bot: Bot) -> None:
    """
    Проверяет скоро-предстоящие записи и шлёт недопосланные напоминания.
    Вызывается планировщиком каждые REMINDER_POLL_INTERVAL_MIN минут.
    """
    appointments = await get_upcoming_appointments()
    now = now_local().replace(tzinfo=None)

    for appt in appointments:
        appt_id: int = appt["id"]
        user_id: int = appt["user_id"]
        service_name: str = appt["service_name"]
        date: str = appt["date"]
        time: str = appt["time"]

        try:
            appointment_dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
        except ValueError:
            logger.warning(
                "Bad date/time in appointment id=%s: date=%r time=%r",
                appt_id, date, time,
            )
            continue

        minutes_left = (appointment_dt - now).total_seconds() / 60

        if REMINDER_24H_MIN <= minutes_left <= REMINDER_24H_MAX:
            if not await was_reminder_sent(appt_id, "reminder_24h"):
                await _send_24h_reminder(bot, user_id, service_name, time, appt_id)
        elif REMINDER_2H_MIN <= minutes_left <= REMINDER_2H_MAX:
            if not await was_reminder_sent(appt_id, "reminder_2h"):
                await _send_2h_reminder(bot, user_id, service_name, time, appt_id)
        elif 0 < minutes_left < REMINDER_2H_MIN:
            # Окно прошло, но визит ещё впереди — бот был оффлайн в нужный момент.
            # Маркируем как «отправленное», чтобы не проверять эту запись каждую итерацию.
            if not await was_reminder_sent(appt_id, "reminder_2h"):
                logger.warning(
                    "Пропущено 2h-напоминание для appointment_id=%s (осталось %.0f мин, бот был оффлайн в окне)",
                    appt_id, minutes_left,
                )
                await mark_reminder_sent(appt_id, "reminder_2h")


async def _send_24h_reminder(
    bot: Bot,
    user_id: int,
    service_name: str,
    time: str,
    appt_id: int,
) -> None:
    from db import get_user_lang
    lang = await get_user_lang(user_id)

    if lang == "uz":
        confirm_btn = "✅ Tasdiqlayman"
        cancel_btn = "❌ Bekor qilish"
        text = (
            f"🔔 <b>ESLATMA</b>\n\n"
            f"Ertaga soat <b>{time}</b>\n"
            f"{h(service_name)}\n\n"
            f"Yozilishni tasdiqlang:"
        )
    else:
        confirm_btn = "✅ Подтверждаю"
        cancel_btn = "❌ Отменить"
        text = (
            f"🔔 <b>НАПОМИНАНИЕ</b>\n\n"
            f"Завтра в <b>{time}</b>\n"
            f"{h(service_name)}\n\n"
            f"Подтвердите запись:"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=confirm_btn, callback_data=f"client_confirm_{appt_id}"),
        InlineKeyboardButton(text=cancel_btn, callback_data=f"client_cancel_{appt_id}"),
    ]])

    try:
        await bot.send_message(user_id, text, reply_markup=kb, parse_mode="HTML")
    except TelegramAPIError:
        logger.warning("Failed to send 24h reminder to user_id=%s (appt=%s)", user_id, appt_id)
        logger.debug("24h reminder error", exc_info=True)
        return

    await mark_reminder_sent(appt_id, "reminder_24h")


async def _send_2h_reminder(
    bot: Bot,
    user_id: int,
    service_name: str,
    time: str,
    appt_id: int,
) -> None:
    from db import get_user_lang
    lang = await get_user_lang(user_id)
    if lang == "uz":
        text = (
            f"⏰ <b>2 SOATDAN KEYIN</b>\n\n"
            f"{h(service_name)}\n"
            f"Vaqt: <b>{time}</b>\n\n"
            f"Kutamiz!"
        )
    else:
        text = (
            f"⏰ <b>ЧЕРЕЗ 2 ЧАСА</b>\n\n"
            f"{h(service_name)}\n"
            f"Время: <b>{time}</b>\n\n"
            f"Ждём!"
        )
    try:
        await bot.send_message(user_id, text, parse_mode="HTML")
    except TelegramAPIError:
        logger.warning("Failed to send 2h reminder to user_id=%s (appt=%s)", user_id, appt_id)
        logger.debug("2h reminder error", exc_info=True)
        return

    await mark_reminder_sent(appt_id, "reminder_2h")


async def run_backup(bot: Bot) -> None:
    """
    Задача бэкапа БД: локальная копия + (опционально) отправка в Telegram-канал.

    Локальный бэкап — первичная копия, всегда. Telegram — страховка от гибели
    диска/дроплета. Ошибка отправки в TG не должна ронять задачу: локальная
    копия уже сделана, это и есть главное.
    """
    # Чистим устаревшие строки ДО бэкапа, чтобы копия не тащила мусор.
    # Ошибка retention не должна блокировать сам бэкап.
    try:
        await _prune_old_rows()
    except Exception:
        logger.warning("retention cleanup упала — продолжаем бэкап", exc_info=True)

    try:
        path = await backup_db()
    except Exception:
        logger.error("Ошибка локального бэкапа", exc_info=True)
        return

    if not path:
        return

    logger.info("Локальный бэкап: %s", path)

    if BACKUP_CHAT_ID is None:
        return

    try:
        size_mb = os.path.getsize(path) / (1024 * 1024)
        timestamp = now_local().strftime("%Y-%m-%d %H:%M")
        caption = f"[{TENANT_SLUG}] backup {timestamp} • {size_mb:.1f} MB"
        await bot.send_document(
            chat_id=BACKUP_CHAT_ID,
            document=FSInputFile(path),
            caption=caption,
        )
        logger.info("Бэкап отправлен в Telegram chat=%s", BACKUP_CHAT_ID)
    except Exception as exc:
        # TG лёг / chat_id кривой / бот выкинут — локальная копия уже есть,
        # это страховка, а не жизненно важный путь.
        logger.warning(
            "Не удалось отправить бэкап в Telegram chat=%s: %s",
            BACKUP_CHAT_ID, exc,
        )




# ─── Проактивный алерт об истечении лицензии ─────────────────────────────────
# Автор получает пуш в ERROR_CHAT_ID за N дней до истечения. Без внешнего
# endpoint'а — используется тот же канал что для ошибок, он у автора уже есть.
# Дедуп через файл-маркер: иначе алерт улетал бы каждые 24ч.

LICENSE_ALERT_DAYS_BEFORE = 60
LICENSE_ALERT_REPEAT_DAYS = 7  # не чаще раза в неделю, чтобы не спамить

LICENSE_ALERT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(DB_PATH)) or ".", ".license_alert",
)


def _license_alert_last_sent() -> datetime | None:
    """Читает timestamp последней отправки из .license_alert.
    None если файла нет или он битый — значит «никогда не слали»."""
    if not os.path.exists(LICENSE_ALERT_PATH):
        return None
    try:
        with open(LICENSE_ALERT_PATH) as f:
            iso = f.read().strip()
        return datetime.fromisoformat(iso)
    except (OSError, ValueError):
        return None


def _license_alert_mark_sent() -> None:
    """Обновляет timestamp в .license_alert. Сбой записи не критичен —
    в худшем случае через сутки придёт дубль-алерт."""
    try:
        with open(LICENSE_ALERT_PATH, "w") as f:
            f.write(datetime.now(timezone.utc).isoformat())
    except OSError:
        logger.warning("Не удалось обновить %s", LICENSE_ALERT_PATH, exc_info=True)


def _should_alert_license(
    license_state: LicenseState, now: datetime,
) -> tuple[bool, int]:
    """Возвращает (надо-слать, days_left). Выделено чистой функцией — тестируется
    без файловой системы и без бота. Правила:
    - нет лицензии (DEV / нет ключа) — не шлём, тестить нечего;
    - days_left > LICENSE_ALERT_DAYS_BEFORE — рано, не слать;
    - days_left <= 0 — уже истекла / в grace, отдельная ветка (warn_grace
      на старте уже есть, дубль тут не нужен);
    - в остальном — слать."""
    if license_state.license is None:
        return False, 0
    expires = license_state.license.expires_at
    days_left = (expires - now).days
    return 0 < days_left <= LICENSE_ALERT_DAYS_BEFORE, days_left


async def alert_license_expiry(bot: Bot, license_state: LicenseState) -> None:
    """Раз в сутки проверяет сколько осталось до истечения лицензии.
    Если <=60 дней и осталось >0 — шлёт пуш в ERROR_CHAT_ID (канал автора).
    Дедуп 7 дней — чтобы не спамить."""
    if ERROR_CHAT_ID is None:
        return
    now = datetime.now(timezone.utc)
    should_alert, days_left = _should_alert_license(license_state, now)
    if not should_alert:
        return

    last = _license_alert_last_sent()
    if last is not None and (now - last).days < LICENSE_ALERT_REPEAT_DAYS:
        return

    lic = license_state.license  # gated by should_alert
    text = (
        f"⏰ <b>[{TENANT_SLUG}]</b> лицензия истекает через <b>{days_left}</b> дн.\n\n"
        f"customer: {h(lic.customer_name)}\n"
        f"license_id: <code>{h(lic.license_id)}</code>\n"
        f"expires_at: <code>{lic.expires_at.date()}</code>\n\n"
        f"Продли до этой даты:\n"
        f"<code>python tools/issue_license.py {h(lic.tenant_slug)} "
        f"\"{h(lic.customer_name)}\" 60</code>"
    )
    try:
        await bot.send_message(chat_id=ERROR_CHAT_ID, text=text, parse_mode="HTML")
        _license_alert_mark_sent()
    except Exception:
        logger.warning("Не удалось отправить license-алерт", exc_info=True)


async def _safe_alert_license_expiry(bot: Bot, license_state: LicenseState) -> None:
    try:
        await alert_license_expiry(bot, license_state)
    except Exception as exc:
        logger.error("alert_license_expiry упала", exc_info=True)
        await report_error(bot, exc, context="scheduler.alert_license_expiry")


# Heartbeat-файл рядом с БД. Healthcheck в docker-compose чекает его mtime.
# Почему не mtime manicure.db: в WAL-режиме SELECT не трогает main-файл, а INSERT
# в sent_reminders случается только когда реально есть что слать. В пустой день
# или ночью mtime БД протухает → false-positive unhealthy. Отдельный heartbeat-файл
# — независимое доказательство, что event loop крутится.
HEARTBEAT_PATH = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)) or ".", ".heartbeat")


async def _touch_heartbeat() -> None:
    """Обновляет mtime heartbeat-файла. Синхронный write — <1ms, async не нужен."""
    try:
        with open(HEARTBEAT_PATH, "w") as f:
            f.write(now_local().isoformat())
    except OSError:
        # Диск полный / права отозваны — фейл heartbeat'а не должен ронять scheduler.
        # Healthcheck сам заметит протухший mtime и пометит контейнер unhealthy.
        logger.warning("Не удалось обновить heartbeat %s", HEARTBEAT_PATH, exc_info=True)


async def _safe_send_reminders(bot: Bot) -> None:
    """Обёртка: любая непойманная ошибка → алерт и лог, но джоба не падает молча."""
    try:
        await send_reminders(bot)
    except Exception as exc:
        logger.error("send_reminders упала", exc_info=True)
        await report_error(bot, exc, context="scheduler.send_reminders")


async def _safe_run_backup(bot: Bot) -> None:
    try:
        await run_backup(bot)
    except Exception as exc:
        logger.error("run_backup упала", exc_info=True)
        await report_error(bot, exc, context="scheduler.run_backup")


def setup_scheduler(bot: Bot, license_state: LicenseState) -> AsyncIOScheduler:
    tz = get_tz()
    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler.add_job(
        _safe_send_reminders,
        trigger="interval",
        minutes=REMINDER_POLL_INTERVAL_MIN,
        args=[bot],
    )
    # Heartbeat для docker healthcheck: каждые 5 мин, сразу при старте.
    # Окно healthcheck в compose — 30 мин, так что 6х запас на случай временных фризов.
    scheduler.add_job(
        _touch_heartbeat,
        trigger="interval",
        minutes=5,
        next_run_time=datetime.now(tz),
    )
    # RPO=6ч: для салона это разница между «потеряли сегодняшние записи»
    # и «потеряли вторую половину дня». Больше — клиентам больно.
    scheduler.add_job(
        _safe_run_backup,
        trigger="interval",
        hours=6,
        args=[bot],
    )
    # Heartbeat: раз в 24ч, первый раз — сразу при старте (не ждём сутки).
    # license_id может быть None (в DEV/RESTRICTED без лицензии) — отправляем пустой.
    # license_expires_at передаём отдельным аргументом, чтобы будущий авторский
    # endpoint мог считать days_until_expiry без парсинга ключа.
    license_id = license_state.license.license_id if license_state.license else None
    license_expires_at = (
        license_state.license.expires_at if license_state.license else None
    )
    scheduler.add_job(
        send_heartbeat,
        trigger="interval",
        hours=24,
        args=[license_id, license_expires_at],
        next_run_time=datetime.now(tz),
    )
    # Проактивный алерт автору об истечении лицензии. Раз в сутки.
    # Дедуп через файл-маркер в задаче — 7 дней между пушами.
    scheduler.add_job(
        _safe_alert_license_expiry,
        trigger="interval",
        hours=24,
        args=[bot, license_state],
        next_run_time=datetime.now(tz),
    )
    return scheduler
