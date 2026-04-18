import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.exceptions import TelegramBadRequest

from constants import format_date_short_ru
from utils.timezone import now_local
from db import (
    get_appointments_by_date_full, get_stats,
    get_services, get_future_blocks, get_all_settings,
    get_all_future_appointments, get_recent_clients, _price_fmt,
    get_all_masters,
)
from keyboards.inline import (
    day_view_keyboard, calendar_keyboard,
    services_list_keyboard, settings_keyboard,
    blocks_list_keyboard, all_appointments_keyboard, clients_menu_keyboard,
    admin_masters_keyboard,
)
from utils.admin import is_admin, is_admin_callback, deny_access, IsAdminFilter
from utils.panel import get_panel_msg_id, set_panel_msg_id, clear_panel_msg_id, get_panel_lock

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(IsAdminFilter())
router.callback_query.filter(IsAdminFilter())

_STATUS_ICON = {"completed": "✅", "no_show": "🚫", "cancelled": "❌"}


# ─── HELPERS ─────────────────────────────────────────────────────────────────


async def _nav(message: Message, text: str, markup=None, parse_mode=None) -> None:
    """
    Удалить тап-сообщение, затем отредактировать существующее навигационное
    сообщение или создать новое и запомнить его ID.
    При ошибке редактирования — УДАЛЯЕТ старое сообщение перед созданием нового.
    Блокировка предотвращает дубли при быстрых кликах.
    Reply keyboard отправляется ТОЛЬКО при /start, здесь НЕ отправляется.
    """
    chat_id = message.chat.id
    lock = get_panel_lock(chat_id)

    async with lock:
        try:
            await message.delete()
        except Exception:
            pass

        nav_id = get_panel_msg_id(chat_id)

        if nav_id:
            try:
                await message.bot.edit_message_text(
                    text,
                    chat_id=chat_id,
                    message_id=nav_id,
                    reply_markup=markup,
                    parse_mode=parse_mode,
                )
                return  # Успешно отредактировали
            except TelegramBadRequest:
                # Не удалось отредактировать — удаляем старое
                try:
                    await message.bot.delete_message(chat_id, nav_id)
                except Exception:
                    pass
                clear_panel_msg_id(chat_id)

        # Панели нет — создаём новую
        sent = await message.bot.send_message(
            chat_id, text,
            reply_markup=markup,
            parse_mode=parse_mode,
        )
        set_panel_msg_id(chat_id, sent.message_id)


async def _nav_day_view(message: Message, date_str: str) -> None:
    all_appts = await get_appointments_by_date_full(date_str)
    try:
        label = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        label = date_str

    if not all_appts:
        await _nav(message, f"📭 На {label} записей нет.")
        return

    scheduled = [a for a in all_appts if a["status"] == "scheduled"]
    archived  = [a for a in all_appts if a["status"] != "scheduled"]

    lines = []
    if scheduled:
        lines.append(f"📅 {label}  •  🟢 В очереди: {len(scheduled)}")
        for a in scheduled:
            lines.append(
                f"\n🕐 {a['time']} — {a['name']}\n"
                f"   📞 {a['phone']}\n"
                f"   💅 {a['service_name']}"
            )
    else:
        lines.append(f"📅 {label}  •  Активных записей нет")

    if archived:
        parts = [
            f"{_STATUS_ICON.get(a['status'], '❓')} {a['time']} {a['name'].split()[0]}"
            for a in archived
        ]
        lines.append(f"\n📁 История: {' | '.join(parts)}")

    await _nav(message, "\n".join(lines), day_view_keyboard(scheduled, date_str))


# ─── admin_home / admin_cancel (inline кнопки из сообщений) ──────────────────

@router.callback_query(F.data == "admin_home")
async def cb_admin_home(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    await state.clear()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
        set_panel_msg_id(callback.message.chat.id, callback.message.message_id)
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data == "notif_dismiss")
async def cb_notif_dismiss(callback: CallbackQuery):
    """Кнопка «✅ Принято» — просто удаляет уведомление из чата."""
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass  # query протух после рестарта бота — это нормально


@router.callback_query(F.data == "notif_all_appointments")
async def cb_notif_all_appointments(callback: CallbackQuery, state: FSMContext):
    """«📒 Все записи» из уведомления — удаляет уведомление, открывает список в панели."""
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    appointments = await get_all_future_appointments()
    if not appointments:
        from utils.panel import edit_panel
        await edit_panel(callback.bot, callback.message.chat.id, "📒 Предстоящих записей нет.", None)
        await callback.answer()
        return
    lines = [f"📒 Предстоящие записи: {len(appointments)}"]
    current_date = None
    for a in appointments:
        if a["date"] != current_date:
            current_date = a["date"]
            date_label = format_date_short_ru(a["date"])
            lines.append(f"\n📅 {date_label}")
        lines.append(f"  🕐 {a['time']} — {a['name']}")
    from utils.panel import edit_panel
    await edit_panel(
        callback.bot, callback.message.chat.id,
        "\n".join(lines), all_appointments_keyboard(appointments),
    )
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass


@router.callback_query(F.data == "admin_all_appointments")
async def cb_admin_all_appointments(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    appointments = await get_all_future_appointments()

    if not appointments:
        text, markup = "📒 Предстоящих записей нет.", None
    else:
        lines = [f"📒 Предстоящие записи: {len(appointments)}"]
        current_date = None
        for a in appointments:
            if a["date"] != current_date:
                current_date = a["date"]
                date_label = format_date_short_ru(a["date"])
                lines.append(f"\n📅 {date_label}")
            lines.append(f"  🕐 {a['time']} — {a['name']}")
        text, markup = "\n".join(lines), all_appointments_keyboard(appointments)

    chat_id = callback.message.chat.id
    panel_id = get_panel_msg_id(chat_id)
    is_notification = panel_id and (callback.message.message_id != panel_id)
    if is_notification:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
        from utils.panel import edit_panel
        await edit_panel(callback.bot, chat_id, text, markup)
    else:
        try:
            await callback.message.edit_text(text, reply_markup=markup)
        except TelegramBadRequest:
            pass
        set_panel_msg_id(chat_id, callback.message.message_id)
    await callback.answer()


@router.callback_query(F.data == "admin_cancel")
async def cb_admin_cancel(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    await state.clear()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
        set_panel_msg_id(callback.message.chat.id, callback.message.message_id)
    except TelegramBadRequest:
        pass
    await callback.answer("Отменено")


@router.message(F.text == "/cancel")
async def cmd_cancel(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    try:
        await message.delete()
    except Exception:
        pass


# ─── КНОПКИ НИЖНЕЙ КЛАВИАТУРЫ ────────────────────────────────────────────────

@router.message(StateFilter("*"), F.text == "📋 Сегодня")
async def msg_today(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await _nav_day_view(message, now_local().strftime("%Y-%m-%d"))


@router.message(StateFilter("*"), F.text == "🗓 Календарь")
async def msg_calendar(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    now = now_local()
    await _nav(message, "🗓 Выберите дату:", calendar_keyboard(now.year, now.month))


@router.message(StateFilter("*"), F.text == "💅 Услуги")
async def msg_services(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    services = await get_services(active_only=False)
    await _nav(message, "💅 Управление услугами:", services_list_keyboard(services))


@router.message(StateFilter("*"), F.text == "📊 Статистика")
async def msg_stats(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    stats = await get_stats()

    conversion_str = f"{stats['conversion']:.0f}%" if stats['conversion'] > 0 else "—"
    avg_check_str = f"{_price_fmt(int(stats['avg_check']))} сум" if stats['avg_check'] > 0 else "—"

    text = (
        "📊 <b>Статистика</b>\n\n"
        f"📅 <b>Сегодня:</b> {stats['today_count']} записей\n"
        f"📆 <b>Эта неделя:</b> {stats['week_count']} записей\n"
        f"🗓 <b>Этот месяц:</b> {stats['month_count']} записей\n\n"
        f"💰 <b>Выручка:</b> {_price_fmt(stats['total_revenue'])} сум\n"
        f"🧾 <b>Средний чек:</b> {avg_check_str}\n"
        f"📈 <b>Конверсия (месяц):</b> {conversion_str}\n"
        f"🔄 <b>Возвраты клиентов:</b> {stats['returning_clients']}\n\n"
        f"✅ Выполнено: {stats['completed_count']}\n"
        f"❌ Отменено: {stats['cancelled_count']}\n"
        f"💅 Популярная: {stats['top_service_name']} ({stats['top_service_count']} визитов)"
    )
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    export_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📥 Экспорт в Excel", callback_data="admin_export"),
    ]])
    await _nav(message, text, export_kb, parse_mode="HTML")


@router.message(StateFilter("*"), F.text == "📒 Все записи")
async def msg_all_appointments(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    appointments = await get_all_future_appointments()
    if not appointments:
        await _nav(message, "📒 Предстоящих записей нет.")
        return

    lines = [f"📒 Предстоящие записи: {len(appointments)}"]
    current_date = None
    for a in appointments:
        if a["date"] != current_date:
            current_date = a["date"]
            date_label = format_date_short_ru(a["date"])
            lines.append(f"\n📅 {date_label}")
        lines.append(f"  🕐 {a['time']} — {a['name']}")

    await _nav(message, "\n".join(lines), all_appointments_keyboard(appointments))


@router.message(StateFilter("*"), F.text == "👥 Клиенты")
async def msg_clients(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    clients = await get_recent_clients(limit=15)
    text = (
        f"👥 Клиенты — последние {len(clients)} по активности"
        if clients else
        "👥 Клиенты\n\nЕщё никто не записывался."
    )
    await _nav(message, text, clients_menu_keyboard(clients))


@router.message(StateFilter("*"), F.text == "⚙️ Настройки")
async def msg_settings(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    s = await get_all_settings()
    await _nav(message, "⚙️ Настройки графика работы:", settings_keyboard(s))


@router.message(StateFilter("*"), F.text == "👨\u200d🎨 Мастера")
async def msg_masters(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    masters = await get_all_masters()
    text = f"👨\u200d🎨 Мастера ({len(masters)})" if masters else "👨\u200d🎨 Мастера\n\nНет ни одного мастера."
    await _nav(message, text, admin_masters_keyboard(masters))


@router.message(StateFilter("*"), F.text == "🚫 Блокировки")
async def msg_blocks(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    blocks = await get_future_blocks()
    text = "📵 Блокировки (будущие):" if blocks else "📵 Блокировок нет."
    await _nav(message, text, blocks_list_keyboard(blocks))
