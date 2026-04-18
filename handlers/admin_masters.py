import logging

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from db import (
    get_all_masters, get_master,
    create_master, update_master, toggle_master_active,
    delete_master,
)
from keyboards.inline import admin_masters_keyboard, master_card_keyboard, admin_cancel_keyboard
from states import AdminStates
from utils.admin import is_admin_callback, is_admin_message, deny_access, IsAdminFilter
from utils.callbacks import parse_callback
from utils.panel import edit_panel, edit_panel_with_callback

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(IsAdminFilter())
router.callback_query.filter(IsAdminFilter())


async def _show_masters(callback: CallbackQuery) -> None:
    masters = await get_all_masters()
    text = f"👨\u200d🎨 Мастера ({len(masters)})" if masters else "👨\u200d🎨 Мастера\n\nНет ни одного мастера."
    await edit_panel_with_callback(callback, text, admin_masters_keyboard(masters))


@router.callback_query(F.data == "admin_masters")
async def cb_admin_masters(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    await state.clear()
    await _show_masters(callback)
    await callback.answer()


@router.callback_query(F.data.startswith("master_card_"))
async def cb_master_card(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "master_card", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    master_id = int(parts[0])
    master = await get_master(master_id)
    if not master:
        await callback.answer("Мастер не найден.", show_alert=True)
        return

    uid_line = f"🆔 TG: {master['user_id']}\n" if master.get("user_id") else "🆔 TG: не привязан\n"
    bio_line = f"📝 {master['bio']}\n" if master.get("bio") else ""
    status = "🟢 Активен" if master["is_active"] else "🔴 Неактивен"

    text = (
        f"👨\u200d🎨 <b>{master['name']}</b>\n\n"
        f"{uid_line}"
        f"{bio_line}"
        f"{status}"
    )
    await edit_panel_with_callback(
        callback, text,
        master_card_keyboard(master_id, bool(master["is_active"])),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("master_toggle_"))
async def cb_master_toggle(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "master_toggle", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    master_id = int(parts[0])
    await toggle_master_active(master_id)
    await cb_master_card(callback)


# ─── УДАЛЕНИЕ МАСТЕРА ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("master_delete_"))
async def cb_master_delete(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "master_delete", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    master_id = int(parts[0])
    success = await delete_master(master_id)
    if not success:
        await callback.answer(
            "Нельзя удалить: у мастера есть история записей. Можно деактивировать.",
            show_alert=True,
        )
        return
    await _show_masters(callback)
    await callback.answer("Мастер удалён.")


# ─── ДОБАВЛЕНИЕ МАСТЕРА ───────────────────────────────────────────────────────

@router.callback_query(F.data == "master_add")
async def cb_master_add(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    await edit_panel_with_callback(callback, "👨\u200d🎨 Введите имя мастера:", admin_cancel_keyboard())
    await state.set_state(AdminStates.master_add_name)
    await callback.answer()


@router.message(AdminStates.master_add_name)
async def msg_master_add_name(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass
    name = message.text.strip() if message.text else ""
    if not name or len(name) < 2:
        await edit_panel(message.bot, message.chat.id, "⚠️ Имя слишком короткое. Введите имя мастера:", admin_cancel_keyboard())
        return
    await state.update_data(master_name=name)
    await edit_panel(
        message.bot, message.chat.id,
        f"👤 Мастер: <b>{name}</b>\n\n"
        "Введите Telegram user_id мастера\n"
        "<i>(узнать можно через @userinfobot — перешлите ему сообщение от мастера)</i>\n\n"
        "Или нажмите /skip чтобы пропустить:",
        admin_cancel_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(AdminStates.master_add_user_id)


@router.message(AdminStates.master_add_user_id)
async def msg_master_add_user_id(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass

    text = message.text.strip() if message.text else ""
    user_id: int | None = None

    if text != "/skip":
        if not text.lstrip("-").isdigit():
            await edit_panel(message.bot, message.chat.id, "⚠️ Введите числовой user_id или /skip:", admin_cancel_keyboard())
            return
        user_id = int(text)

    await state.update_data(master_user_id=user_id)
    await edit_panel(
        message.bot, message.chat.id,
        "📝 Введите краткое описание мастера (специализация, стаж и т.п.)\n\nИли /skip:",
        admin_cancel_keyboard(),
    )
    await state.set_state(AdminStates.master_add_bio)


@router.message(AdminStates.master_add_bio)
async def msg_master_add_bio(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass

    text = message.text.strip() if message.text else ""
    bio = "" if text == "/skip" else text

    data = await state.get_data()
    master_id = await create_master(
        user_id=data.get("master_user_id"),
        name=data["master_name"],
        bio=bio,
    )
    await state.clear()

    master = await get_master(master_id)
    masters = await get_all_masters()
    await edit_panel(
        message.bot, message.chat.id,
        f"✅ Мастер <b>{master['name']}</b> добавлен.\n\n"
        f"👨\u200d🎨 Мастера ({len(masters)})",
        admin_masters_keyboard(masters),
        parse_mode="HTML",
    )


# ─── РЕДАКТИРОВАНИЕ ──────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("master_edit_name_"))
async def cb_master_edit_name(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "master_edit_name", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    master_id = int(parts[0])
    await state.update_data(edit_master_id=master_id)
    await edit_panel_with_callback(callback, "✏️ Введите новое имя:", admin_cancel_keyboard())
    await state.set_state(AdminStates.master_edit_name)
    await callback.answer()


@router.message(AdminStates.master_edit_name)
async def msg_master_edit_name(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass
    name = message.text.strip() if message.text else ""
    if not name or len(name) < 2:
        await edit_panel(message.bot, message.chat.id, "⚠️ Имя слишком короткое:", admin_cancel_keyboard())
        return
    data = await state.get_data()
    master_id = data["edit_master_id"]
    await update_master(master_id, name=name)
    await state.clear()
    master = await get_master(master_id)
    await edit_panel(
        message.bot, message.chat.id,
        f"✅ Имя обновлено: <b>{master['name']}</b>",
        master_card_keyboard(master_id, bool(master["is_active"])),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("master_edit_uid_"))
async def cb_master_edit_uid(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "master_edit_uid", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    master_id = int(parts[0])
    await state.update_data(edit_master_id=master_id)
    await edit_panel_with_callback(
        callback,
        "🆔 Введите новый Telegram user_id мастера\nИли /skip чтобы убрать привязку:",
        admin_cancel_keyboard(),
    )
    await state.set_state(AdminStates.master_edit_user_id)
    await callback.answer()


@router.message(AdminStates.master_edit_user_id)
async def msg_master_edit_user_id(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass
    text = message.text.strip() if message.text else ""
    user_id: int | None = None
    if text != "/skip":
        if not text.lstrip("-").isdigit():
            await edit_panel(message.bot, message.chat.id, "⚠️ Введите числовой user_id или /skip:", admin_cancel_keyboard())
            return
        user_id = int(text)
    data = await state.get_data()
    master_id = data["edit_master_id"]
    await update_master(master_id, user_id=user_id)
    await state.clear()
    master = await get_master(master_id)
    await edit_panel(
        message.bot, message.chat.id,
        "✅ User ID обновлён.",
        master_card_keyboard(master_id, bool(master["is_active"])),
    )


@router.callback_query(F.data.startswith("master_edit_bio_"))
async def cb_master_edit_bio(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "master_edit_bio", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    master_id = int(parts[0])
    await state.update_data(edit_master_id=master_id)
    await edit_panel_with_callback(callback, "📝 Введите новое описание (или /skip чтобы очистить):", admin_cancel_keyboard())
    await state.set_state(AdminStates.master_edit_bio)
    await callback.answer()


@router.message(AdminStates.master_edit_bio)
async def msg_master_edit_bio(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass
    text = message.text.strip() if message.text else ""
    bio = "" if text == "/skip" else text
    data = await state.get_data()
    master_id = data["edit_master_id"]
    await update_master(master_id, bio=bio)
    await state.clear()
    master = await get_master(master_id)
    await edit_panel(
        message.bot, message.chat.id,
        "✅ Описание обновлено.",
        master_card_keyboard(master_id, bool(master["is_active"])),
    )
