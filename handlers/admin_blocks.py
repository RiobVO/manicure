import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from states import AdminStates
from db import get_future_blocks, add_day_off, add_time_block, delete_blocked_slot, get_active_masters
from keyboards.inline import (
    blocks_list_keyboard, block_date_keyboard, block_type_keyboard,
    block_delete_confirm_keyboard, admin_cancel_keyboard,
    block_master_select_keyboard,
)
from utils.admin import is_admin_callback, is_admin_message, deny_access, IsAdminFilter
from utils.callbacks import parse_callback
from utils.panel import edit_panel, edit_panel_with_callback
from utils.validators import validate_time

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(IsAdminFilter())
router.callback_query.filter(IsAdminFilter())


async def _show_blocks(callback: CallbackQuery) -> None:
    blocks = await get_future_blocks()
    text = "📵 Блокировки (будущие):" if blocks else "📵 Блокировок нет."
    await edit_panel_with_callback(callback, text, blocks_list_keyboard(blocks))


@router.callback_query(F.data == "admin_blocks")
async def cb_admin_blocks(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    await _show_blocks(callback)


# ─── УДАЛЕНИЕ: сначала подтверждение ─────────────────────────────────────────

@router.callback_query(F.data.startswith("block_delete_") & ~F.data.startswith("block_delete_confirm_"))
async def cb_block_delete_ask(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "block_delete", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    block_id = int(parts[0])
    await edit_panel_with_callback(
        callback,
        "❓ Удалить эту блокировку?",
        block_delete_confirm_keyboard(block_id),
    )


@router.callback_query(F.data.startswith("block_delete_confirm_"))
async def cb_block_delete_confirm(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "block_delete_confirm", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    block_id = int(parts[0])
    await delete_blocked_slot(block_id)
    await _show_blocks(callback)


# ─── ДОБАВЛЕНИЕ БЛОКИРОВКИ ────────────────────────────────────────────────────

@router.callback_query(F.data == "block_add")
async def cb_block_add(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    masters = await get_active_masters()
    if masters:
        await edit_panel_with_callback(
            callback,
            "📵 Для кого создать блокировку?",
            block_master_select_keyboard(masters),
        )
        await state.set_state(AdminStates.block_pick_master)
    else:
        # Нет мастеров — сразу к дате, master_id=None
        await state.update_data(block_master_id=None)
        await edit_panel_with_callback(callback, "📵 Выберите дату для блокировки:", block_date_keyboard())
        await state.set_state(AdminStates.block_pick_date)
    await callback.answer()


@router.callback_query(AdminStates.block_pick_master, F.data.startswith("block_master_"))
async def cb_block_master(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "block_master", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    raw = parts[0]
    master_id = None if raw == "all" else int(raw)
    await state.update_data(block_master_id=master_id)
    await edit_panel_with_callback(callback, "📵 Выберите дату для блокировки:", block_date_keyboard())
    await state.set_state(AdminStates.block_pick_date)
    await callback.answer()


@router.callback_query(AdminStates.block_pick_date, F.data.startswith("block_date_"))
async def cb_block_date(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "block_date", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    date_str = parts[0]
    await state.update_data(block_date=date_str)
    await edit_panel_with_callback(
        callback,
        f"📵 Дата: {date_str}\nВыберите тип блокировки:",
        block_type_keyboard(date_str),
    )
    await state.set_state(AdminStates.block_pick_type)
    await callback.answer()


@router.callback_query(AdminStates.block_pick_type, F.data.startswith("block_type_dayoff_"))
async def cb_block_type_dayoff(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "block_type_dayoff", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    date_str = parts[0]
    data = await state.get_data()
    master_id = data.get("block_master_id")
    await add_day_off(date_str, master_id=master_id)
    await state.clear()
    await callback.answer("Выходной добавлен.", show_alert=False)
    await _show_blocks(callback)


@router.callback_query(AdminStates.block_pick_type, F.data.startswith("block_type_range_"))
async def cb_block_type_range(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "block_type_range", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    date_str = parts[0]
    await state.update_data(block_date=date_str)
    await edit_panel_with_callback(
        callback,
        f"⏰ Дата: {date_str}\nВведите начало блокировки в формате ЧЧ:ММ\nНапример: 12:00",
        admin_cancel_keyboard(),
    )
    await state.set_state(AdminStates.block_pick_time_start)
    await callback.answer()


@router.message(AdminStates.block_pick_time_start)
async def msg_block_time_start(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass
    text = message.text.strip() if message.text else ""
    parsed_time = validate_time(text)
    if parsed_time is None:
        await edit_panel(message.bot, message.chat.id, "⚠️ Введите время в формате ЧЧ:ММ, например: 12:00", admin_cancel_keyboard())
        return
    await state.update_data(block_time_start=text)
    await edit_panel(message.bot, message.chat.id, "⏰ Введите конец блокировки в формате ЧЧ:ММ:", admin_cancel_keyboard())
    await state.set_state(AdminStates.block_pick_time_end)


@router.message(AdminStates.block_pick_time_end)
async def msg_block_time_end(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass
    text = message.text.strip() if message.text else ""
    parsed_time = validate_time(text)
    if parsed_time is None:
        await edit_panel(message.bot, message.chat.id, "⚠️ Введите время в формате ЧЧ:ММ, например: 18:00", admin_cancel_keyboard())
        return

    data = await state.get_data()
    time_start = data["block_time_start"]
    date_str = data["block_date"]
    master_id = data.get("block_master_id")

    if text <= time_start:
        await edit_panel(message.bot, message.chat.id, f"⚠️ Конец блокировки должен быть позже начала ({time_start}):", admin_cancel_keyboard())
        return

    await add_time_block(date_str, time_start, text, master_id=master_id)
    await state.clear()

    blocks = await get_future_blocks()
    text_list = "📵 Блокировки (будущие):" if blocks else "📵 Блокировок нет."
    await edit_panel(
        message.bot, message.chat.id,
        f"✅ Блокировка добавлена: {date_str} {time_start}–{text}\n\n{text_list}",
        blocks_list_keyboard(blocks),
    )
