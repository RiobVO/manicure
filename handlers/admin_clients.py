import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from states import AdminStates
from db import (
    get_recent_clients, search_clients, get_dormant_clients, get_client_card,
    get_appointment_by_id,
)
from keyboards.inline import (
    clients_menu_keyboard, client_card_keyboard, admin_cancel_keyboard,
    appointment_actions_keyboard, STATUS_EMOJI,
)
from utils.admin import STATUS_LABEL, is_admin_callback, is_admin_message, deny_access, IsAdminFilter
from utils.callbacks import parse_callback
from utils.panel import edit_panel, edit_panel_with_callback

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(IsAdminFilter())
router.callback_query.filter(IsAdminFilter())


@router.callback_query(F.data == "admin_clients")
async def cb_admin_clients(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    await state.clear()
    clients = await get_recent_clients(limit=15)
    text = (
        f"👥 Клиенты — последние {len(clients)} по активности"
        if clients else
        "👥 Клиенты\n\nЕщё никто не записывался."
    )
    await edit_panel_with_callback(callback, text, clients_menu_keyboard(clients))
    await callback.answer()


@router.callback_query(F.data == "admin_clients_search")
async def cb_admin_clients_search(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    await edit_panel_with_callback(
        callback,
        "🔍 Введите имя или номер телефона:",
        admin_cancel_keyboard(),
    )
    await state.set_state(AdminStates.client_search)
    await callback.answer()


@router.message(AdminStates.client_search)
async def msg_client_search(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return

    try:
        await message.delete()
    except Exception:
        pass

    query = message.text.strip() if message.text else ""
    if not query:
        await edit_panel(
            message.bot, message.chat.id,
            "⚠️ Введите имя или телефон:",
            admin_cancel_keyboard(),
        )
        return

    clients = await search_clients(query)
    await state.clear()

    if not clients:
        await edit_panel(
            message.bot, message.chat.id,
            f"👥 По запросу «{query}» ничего не найдено.",
            InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔍 Новый поиск", callback_data="admin_clients_search"),
                InlineKeyboardButton(text="🔙 Клиенты", callback_data="admin_clients"),
            ]]),
        )
        return

    await edit_panel(
        message.bot, message.chat.id,
        f"🔍 «{query}»: {len(clients)} найдено",
        clients_menu_keyboard(clients, show_dormant=False),
    )


@router.callback_query(F.data == "admin_clients_dormant")
async def cb_admin_clients_dormant(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return

    clients = await get_dormant_clients(days=30)
    if not clients:
        await callback.answer("Все клиенты были недавно!", show_alert=True)
        return

    await edit_panel_with_callback(
        callback,
        f"🕐 Не приходили 30+ дней: {len(clients)} чел.",
        clients_menu_keyboard(clients, show_dormant=False),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("client_card_"))
async def cb_client_card(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return

    parts = parse_callback(callback.data, "client_card", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    user_id = int(parts[0])
    card = await get_client_card(user_id)

    if not card:
        await callback.answer("Клиент не найден.", show_alert=True)
        return

    last_visit = card.get("last_visit") or "—"
    if last_visit != "—":
        try:
            dt = datetime.strptime(last_visit, "%Y-%m-%d")
            last_visit = f"{dt.day:02d}.{dt.month:02d}.{dt.year}"
        except ValueError:
            pass

    price_fmt = f"{card.get('total_spent', 0):,}".replace(",", " ")
    fav = card.get("fav_service") or "—"
    upcoming = card.get("upcoming_count", 0)

    lines = [
        f"👤 {card['name']}",
        f"📞 {card['phone']}",
        "",
        f"✅ Визитов завершено: {card['completed_count']}",
        f"📅 Последний визит: {last_visit}",
        f"💅 Любимая услуга: {fav}",
        f"💰 Потрачено: {price_fmt} сум",
    ]
    if upcoming:
        lines.append(f"🗓 Предстоящих записей: {upcoming}")

    recent = card.get("recent_appointments", [])
    if recent:
        lines.append("")
        lines.append("📋 Последние записи:")
        for appt in recent:
            try:
                dt = datetime.strptime(appt["date"], "%Y-%m-%d")
                date_label = f"{dt.day:02d}.{dt.month:02d}"
            except ValueError:
                date_label = appt["date"]
            emoji = STATUS_EMOJI.get(appt["status"], "")
            lines.append(f"• {date_label} {appt['time']} — {appt['service_name']} {emoji}")

    await edit_panel_with_callback(callback, "\n".join(lines), client_card_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("appt_detail_"))
async def cb_appt_detail(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return

    parts = parse_callback(callback.data, "appt_detail", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    appt_id = int(parts[0])
    appt = await get_appointment_by_id(appt_id)

    if not appt:
        await callback.answer("Запись не найдена.", show_alert=True)
        return

    status = STATUS_LABEL.get(appt["status"], appt["status"])
    master_line = f"\n👨\u200d🎨 {appt['master_name']}" if appt.get("master_name") else ""
    from utils.payment_ui import payment_pill
    text = (
        f"📋 Запись #{appt['id']}\n\n"
        f"👤 {appt['name']}\n"
        f"📞 {appt['phone']}\n"
        f"💅 {appt['service_name']}\n"
        f"📅 {appt['date']} в {appt['time']}"
        f"{master_line}\n"
        f"📌 {status}"
        f"{payment_pill(appt)}"
    )
    await edit_panel_with_callback(
        callback,
        text,
        appointment_actions_keyboard(appt_id, appt["date"], appt["status"]),
    )
    await callback.answer()
