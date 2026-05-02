"""
Управление админами через команды.
Только главный админ (из .env) может добавлять/удалять.
"""
import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from config import ADMIN_IDS
from db import add_admin, remove_admin, get_db_admins, log_admin_action
from utils.admin import refresh_admins_cache, is_admin_message, deny_access_msg, IsAdminFilter

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(IsAdminFilter())
router.callback_query.filter(IsAdminFilter())


def _is_owner(user_id: int) -> bool:
    """Только .env админы могут управлять другими админами."""
    return user_id in ADMIN_IDS


@router.message(F.text == "/admins")
async def cmd_admins(message: Message):
    if not _is_owner(message.from_user.id):
        await message.answer("🚫 Только владелец может управлять админами.")
        return

    env_admins = ", ".join(str(a) for a in sorted(ADMIN_IDS))
    db_admins = await get_db_admins()

    if not db_admins:
        await message.answer(
            f"👑 <b>Админы</b>\n\n"
            f"🔑 Владелец (из .env): <code>{env_admins}</code>\n\n"
            f"📌 Дополнительных админов нет.\n\n"
            f"<b>Команды:</b>\n"
            f"/add_admin &lt;user_id&gt; — добавить\n"
            f"/remove_admin &lt;user_id&gt; — удалить",
            parse_mode="HTML",
        )
        return

    lines = [f"👑 <b>Админы</b>\n\n🔑 Владелец (из .env): <code>{env_admins}</code>\n"]
    for a in db_admins:
        added = a["added_at"][:16].replace("T", " ")
        comment = f" — {a['comment']}" if a.get("comment") else ""
        lines.append(f"• <code>{a['user_id']}</code> (добавлен {added}{comment})")

    lines.append(
        f"\n<b>Команды:</b>\n"
        f"/add_admin &lt;user_id&gt; [коммент] — добавить\n"
        f"/remove_admin &lt;user_id&gt; — удалить"
    )

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(F.text.startswith("/add_admin"))
async def cmd_add_admin(message: Message):
    if not _is_owner(message.from_user.id):
        await message.answer("🚫 Только владелец может добавлять админов.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(
            "✏️ Использование:\n"
            "<code>/add_admin &lt;user_id&gt; [комментарий]</code>\n\n"
            "Пример: <code>/add_admin 123456789 менеджер</code>",
            parse_mode="HTML",
        )
        return

    try:
        user_id = int(parts[1])
    except ValueError:
        await message.answer("⚠️ user_id должен быть числом.")
        return

    comment = " ".join(parts[2:]) if len(parts) > 2 else ""

    await add_admin(user_id, message.from_user.id, comment)
    await refresh_admins_cache()
    await log_admin_action(
        admin_id=message.from_user.id,
        action="add_admin",
        target_type="admin",
        target_id=user_id,
        details=f"Добавлен как админ{': ' + comment if comment else ''}",
    )

    await message.answer(f"✅ <b>{user_id}</b> добавлен как админ.", parse_mode="HTML")


@router.message(F.text.startswith("/remove_admin"))
async def cmd_remove_admin(message: Message):
    if not _is_owner(message.from_user.id):
        await message.answer("🚫 Только владелец может удалять админов.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(
            "✏️ Использование:\n<code>/remove_admin &lt;user_id&gt;</code>",
            parse_mode="HTML",
        )
        return

    try:
        user_id = int(parts[1])
    except ValueError:
        await message.answer("⚠️ user_id должен быть числом.")
        return

    if user_id in ADMIN_IDS:
        await message.answer("🚫 Нельзя удалить владельца (из .env).")
        return

    removed = await remove_admin(user_id)
    await refresh_admins_cache()

    if removed:
        await log_admin_action(
            admin_id=message.from_user.id,
            action="remove_admin",
            target_type="admin",
            target_id=user_id,
            details="Удалён из админов",
        )
        await message.answer(f"✅ <b>{user_id}</b> удалён из админов.", parse_mode="HTML")
    else:
        await message.answer(f"❌ <b>{user_id}</b> не найден в списке админов.", parse_mode="HTML")
