"""
Shared admin utilities: guards, labels, helpers.
Import from here to avoid duplication across admin handlers.
"""
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message, TelegramObject
from config import ADMIN_IDS
from db import is_db_admin

STATUS_LABEL: dict[str, str] = {
    "scheduled": "🕐 Ожидает",
    "completed": "✅ Выполнено",
    "no_show":   "🚫 Не пришёл",
    "cancelled":  "❌ Отменено",
}


def is_admin(user_id: int) -> bool:
    """Проверяет админа: из .env или из БД."""
    return user_id in ADMIN_IDS or user_id in _db_admins_cache


def all_admin_ids() -> set[int]:
    """Объединение env-админов и DB-кэша. Используется для push-рассылок."""
    return set(ADMIN_IDS) | _db_admins_cache


_db_admins_cache: set[int] = set()


async def refresh_admins_cache() -> None:
    """Обновить кэш админов из БД."""
    global _db_admins_cache
    from db import get_db_admins
    admins = await get_db_admins()
    _db_admins_cache = {a["user_id"] for a in admins}


def is_admin_callback(callback: CallbackQuery) -> bool:
    return is_admin(callback.from_user.id)


def is_admin_message(message: Message) -> bool:
    return is_admin(message.from_user.id)


async def deny_access(callback: CallbackQuery) -> None:
    """Shortcut: отказ в доступе + answer()."""
    await callback.answer("Доступ запрещён.", show_alert=True)


async def deny_access_msg(message: Message) -> None:
    """Shortcut: отказ в доступе для message."""
    await message.answer("🚫 Доступ запрещён.")


class IsAdminFilter(BaseFilter):
    """Фильтр роутер-уровня: пропускает только админов (из .env или БД)."""

    async def __call__(self, event: TelegramObject) -> bool:
        user = getattr(event, "from_user", None)
        if user is None:
            return False
        return is_admin(user.id)
