"""Уведомления мастерам и клиентам."""
import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from db.masters import get_master
from utils.admin import all_admin_ids, is_admin

logger = logging.getLogger(__name__)


def _master_dismiss_kb() -> InlineKeyboardMarkup:
    """Inline-кнопка «Принято» — чистит мастерское уведомление из чата.
    Callback `notif_dismiss` уже обрабатывается в admin.py (удаляет сообщение)."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Принято", callback_data="notif_dismiss"),
    ]])


def admin_dismiss_kb(label: str = "✅ Ок") -> InlineKeyboardMarkup:
    """Стандартная кнопка закрытия для admin-broadcast'ов — оплата, отмена,
    refund-алерт. Без неё сообщения накапливаются в чате и мешают работать
    с живой панелью. callback=notif_dismiss обрабатывается в admin.py."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=label, callback_data="notif_dismiss"),
    ]])

# Шаблоны сообщений мастеру
_MASTER_TEMPLATES: dict[str, str] = {
    "new_booking": "📋 Новая запись!\n{date} в {time}\nКлиент: {client_name}\nУслуга: {service_name}",
    "cancelled": "❌ Запись отменена\n{date} в {time}\nКлиент: {client_name}",
    "rescheduled": "🔄 Запись перенесена\nНовая дата: {date} в {time}\nКлиент: {client_name}",
}

# Шаблоны сообщений клиенту.
# Для cancelled_by_master / rescheduled_by_master добавляем master_name в data,
# чтобы клиент знал КТО инициировал изменение (в салоне 2+ мастера — важно,
# клиент должен понимать к кому переносить разговор).
_CLIENT_TEMPLATES: dict[str, str] = {
    "status_changed": "📌 Статус записи на {date} обновлён\nНовый статус: {status}",
    "rescheduled": "🔄 Ваша запись перенесена\nНовая дата: {date} в {time}",
    "cancelled_by_master": (
        "❌ Мастер {master_name} отменил(а) вашу запись.\n\n"
        "📅 Было: {date} в {time}\n"
        "💅 {service_name}\n\n"
        "Свяжитесь с салоном для переноса на другое время."
    ),
    "rescheduled_by_master": (
        "🔄 Мастер {master_name} перенёс(ла) вашу запись.\n\n"
        "📅 Было: {old_date} в {old_time}\n"
        "📅 Стало: {date} в {time}\n"
        "💅 {service_name}\n\n"
        "Если неудобно — ответьте на это сообщение или свяжитесь с салоном."
    ),
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

    # Дедуп: если мастер одновременно админ — админский broadcast уже ушёл
    # ему же как админу (с кнопками «✅ Принято» / «📒 Все записи»).
    # Повторять тот же факт мастерским шаблоном без кнопок — мусор в чате.
    if is_admin(master["user_id"]):
        logger.debug(
            "Мастер id=%s = админ (user_id=%s), пропускаем master-уведомление (событие %s)",
            master_id, master["user_id"], event,
        )
        return False

    text = template.format(**data)
    try:
        await bot.send_message(
            master["user_id"],
            text,
            reply_markup=_master_dismiss_kb(),
        )
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
