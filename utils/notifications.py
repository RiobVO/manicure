"""Уведомления мастерам и клиентам."""
import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup

from db.masters import get_master
from utils.admin import all_admin_ids

logger = logging.getLogger(__name__)

# Шаблоны сообщений мастеру
_MASTER_TEMPLATES: dict[str, str] = {
    "new_booking": "📋 Новая запись!\n{date} в {time}\nКлиент: {client_name}\nУслуга: {service_name}",
    "cancelled": "❌ Запись отменена\n{date} в {time}\nКлиент: {client_name}",
    "rescheduled": "🔄 Запись перенесена\nНовая дата: {date} в {time}\nКлиент: {client_name}",
}

# Шаблоны сообщений клиенту
_CLIENT_TEMPLATES: dict[str, str] = {
    "status_changed": "📌 Статус записи на {date} обновлён\nНовый статус: {status}",
    "rescheduled": "🔄 Ваша запись перенесена\nНовая дата: {date} в {time}",
}


async def broadcast_to_admins(
    bot: Bot,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = "HTML",
    log_context: str = "admin broadcast",
) -> None:
    """
    Рассылка всем админам (из .env и БД) параллельно.

    Параллельно — потому что последовательный цикл упирался в лаг Telegram
    при каждом send_message. gather с return_exceptions=True гарантирует,
    что падение одного не обрывает остальных.
    """
    admin_ids = all_admin_ids()
    if not admin_ids:
        return

    async def _one(admin_id: int) -> None:
        await bot.send_message(admin_id, text, reply_markup=reply_markup, parse_mode=parse_mode)

    results = await asyncio.gather(
        *(_one(aid) for aid in admin_ids),
        return_exceptions=True,
    )
    for admin_id, result in zip(admin_ids, results):
        if isinstance(result, Exception):
            logger.warning(
                "Failed to notify admin %s (%s): %s",
                admin_id, log_context, result,
            )


async def notify_master(bot: Bot, master_id: int | None, event: str, data: dict) -> bool:
    """Уведомляет мастера о событии с записью.

    master_id — ID из таблицы masters (не telegram user_id).
    Events: 'new_booking', 'cancelled', 'rescheduled'
    data: dict с ключами date, time, client_name, service_name
    """
    if master_id is None:
        return False

    template = _MASTER_TEMPLATES.get(event)
    if not template:
        logger.warning("Неизвестный тип события мастера: %s", event)
        return False

    master = await get_master(master_id)
    if not master or not master.get("user_id"):
        logger.warning("Мастер id=%s не найден или не привязан к Telegram", master_id)
        return False

    text = template.format(**data)
    try:
        await bot.send_message(master["user_id"], text)
        return True
    except TelegramForbiddenError:
        logger.warning("Мастер id=%s заблокировал бота", master_id)
        return False
    except TelegramBadRequest as exc:
        logger.warning("Ошибка отправки мастеру id=%s: %s", master_id, exc)
        return False
    except Exception:
        logger.error("Непредвиденная ошибка при уведомлении мастера id=%s", master_id, exc_info=True)
        return False


async def notify_client(bot: Bot, user_id: int, event: str, data: dict) -> bool:
    """Уведомляет клиента о событии с записью.

    user_id — telegram user_id клиента.
    Events: 'status_changed', 'rescheduled'
    data: dict с ключами date, time, status (для status_changed)
    """
    template = _CLIENT_TEMPLATES.get(event)
    if not template:
        logger.warning("Неизвестный тип события клиента: %s", event)
        return False

    text = template.format(**data)
    try:
        await bot.send_message(user_id, text)
        return True
    except TelegramForbiddenError:
        logger.warning("Клиент user_id=%s заблокировал бота", user_id)
        return False
    except TelegramBadRequest as exc:
        logger.warning("Ошибка отправки клиенту user_id=%s: %s", user_id, exc)
        return False
    except Exception:
        logger.error("Непредвиденная ошибка при уведомлении клиента user_id=%s", user_id, exc_info=True)
        return False
