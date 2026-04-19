"""
Планировщик напоминаний с дедупликацией.

Типы напоминаний:
  • reminder_24h  — за 20-28 часов до визита
  • reminder_2h   — за 1.5-2.5 часа до визита

Окна и интервал опроса — в constants.py.
"""
import logging
import os
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BACKUP_CHAT_ID, TENANT_SLUG
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
    """
    db = await get_db()
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
    await db.commit()
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
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтверждаю", callback_data=f"client_confirm_{appt_id}"),
            InlineKeyboardButton(text="❌ Отменить", callback_data=f"client_cancel_{appt_id}"),
        ]
    ])

    try:
        await bot.send_message(
            user_id,
            f"<i>доброе утро ☼</i>\n\n"
            f"завтра в <b>{time}</b> жду тебя ✧\n"
            f"{service_name.lower()}\n\n"
            f"<i>всё в силе?</i>",
            reply_markup=kb,
            parse_mode="HTML",
        )
    except TelegramAPIError:
        # Заблокирован/не существует чат — полный стек в DEBUG, одну строку в WARNING.
        logger.warning(
            "Failed to send 24h reminder to user_id=%s (appt=%s)",
            user_id, appt_id,
        )
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
    try:
        await bot.send_message(
            user_id,
            f"<i>через час-два приходи ✦</i>\n\n"
            f"{service_name.lower()} · <b>{time}</b>",
            parse_mode="HTML",
        )
    except TelegramAPIError:
        logger.warning(
            "Failed to send 2h reminder to user_id=%s (appt=%s)",
            user_id, appt_id,
        )
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
    license_id = license_state.license.license_id if license_state.license else None
    scheduler.add_job(
        send_heartbeat,
        trigger="interval",
        hours=24,
        args=[license_id],
        next_run_time=datetime.now(tz),
    )
    return scheduler
