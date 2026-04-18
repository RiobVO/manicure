"""
Планировщик напоминаний с дедупликацией.

Типы напоминаний:
  • reminder_24h  — за 20-28 часов до визита
  • reminder_2h   — за 1.5-2.5 часа до визита

Окна и интервал опроса — в constants.py.
"""
import logging
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from constants import (
    REMINDER_2H_MAX,
    REMINDER_2H_MIN,
    REMINDER_24H_MAX,
    REMINDER_24H_MIN,
    REMINDER_POLL_INTERVAL_MIN,
    format_date_ru,
)
from utils.timezone import now_local, get_tz
from db import (
    get_upcoming_appointments,
    mark_reminder_sent,
    was_reminder_sent,
)
from db.connection import backup_db

logger = logging.getLogger(__name__)


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
        name: str = appt["name"]
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
                await _send_24h_reminder(bot, user_id, name, service_name, date, time, appt_id)
        elif REMINDER_2H_MIN <= minutes_left <= REMINDER_2H_MAX:
            if not await was_reminder_sent(appt_id, "reminder_2h"):
                await _send_2h_reminder(bot, user_id, name, service_name, date, time, appt_id)
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
    name: str,
    service_name: str,
    date: str,
    time: str,
    appt_id: int,
) -> None:
    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
        date_str = format_date_ru(dt.day, dt.month)
    except ValueError:
        date_str = date

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтверждаю", callback_data=f"client_confirm_{appt_id}"),
            InlineKeyboardButton(text="❌ Отменить", callback_data=f"client_cancel_{appt_id}"),
        ]
    ])

    try:
        await bot.send_message(
            user_id,
            f"📅 <b>Напоминание: завтра визит!</b>\n\n"
            f"Привет, {name}! Завтра в <b>{time}</b> у вас запись:\n"
            f"💅 {service_name}\n"
            f"📍 Ждём вас {date_str} в {time}!\n\n"
            f"Подтвердите или отмените запись:",
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
    name: str,
    service_name: str,
    date: str,
    time: str,
    appt_id: int,
) -> None:
    try:
        await bot.send_message(
            user_id,
            f"⏰ <b>Напоминание: скоро визит!</b>\n\n"
            f"Привет, {name}! Сегодня в <b>{time}</b> у вас запись:\n"
            f"💅 {service_name}\n\n"
            f"Ждём вас! 🙂",
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


async def run_backup() -> None:
    """Задача бэкапа БД."""
    try:
        result = await backup_db()
        if result:
            logger.info("Бэкап создан: %s", result)
    except Exception:
        logger.error("Ошибка бэкапа", exc_info=True)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    tz = get_tz()
    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler.add_job(
        send_reminders,
        trigger="interval",
        minutes=REMINDER_POLL_INTERVAL_MIN,
        args=[bot],
    )
    scheduler.add_job(
        run_backup,
        trigger="interval",
        hours=24,
    )
    return scheduler
