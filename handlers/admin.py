import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.exceptions import TelegramBadRequest

from utils.timezone import now_local
from db import (
    get_appointments_by_date_full,
    get_services, get_future_blocks, get_all_settings,
    get_all_future_appointments, get_recent_clients, _price_fmt,
    get_all_masters,
)
from keyboards.inline import (
    day_view_keyboard, calendar_keyboard,
    services_list_keyboard, settings_keyboard,
    blocks_list_keyboard, all_appointments_keyboard, clients_menu_keyboard,
    admin_masters_keyboard, admin_reply_keyboard,
    APPTS_PER_PAGE,
)
from utils.admin import is_admin, is_admin_callback, deny_access, IsAdminFilter
from utils.panel import (
    get_panel_msg_id, set_panel_msg_id, clear_panel_msg_id, get_panel_lock,
    delete_in_bg, set_reply_kb,
)

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

    # delete тап-сообщения не блокирует навигацию — экономит ~240мс TG round-trip.
    delete_in_bg(message)

    async with lock:
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
    # ack до TG-вызова: иначе у клиента крутятся часики весь RTT edit_reply_markup.
    await callback.answer()
    await state.clear()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
        set_panel_msg_id(callback.message.chat.id, callback.message.message_id)
    except TelegramBadRequest:
        pass


@router.callback_query(F.data == "notif_dismiss")
async def cb_notif_dismiss(callback: CallbackQuery):
    """Кнопка «✅ Принято» — просто удаляет уведомление из чата."""
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    try:
        await callback.answer()  # ранний ack — часики уходят сразу
    except TelegramBadRequest:
        pass  # query протух после рестарта бота — это нормально
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass


def _all_appts_text(appointments: list[dict], page: int) -> str:
    """Текст экрана «Все записи». Поденная разбивка убрана: каждая кнопка
    ниже уже несёт дату+время+имя, дублировать в тексте бессмысленно."""
    if not appointments:
        return "📒 Предстоящих записей нет."
    total = len(appointments)
    per_page = APPTS_PER_PAGE
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    if total_pages == 1:
        return f"📒 Предстоящие записи: {total}"
    return f"📒 Предстоящие записи: {total} · стр. {page + 1}/{total_pages}"


@router.callback_query(F.data == "notif_all_appointments")
async def cb_notif_all_appointments(callback: CallbackQuery, state: FSMContext):
    """«📒 Все записи» из уведомления — удаляет уведомление, открывает список в панели."""
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    appointments = await get_all_future_appointments()
    from utils.panel import edit_panel
    await edit_panel(
        callback.bot, callback.message.chat.id,
        _all_appts_text(appointments, page=0),
        all_appointments_keyboard(appointments, page=0),
    )


@router.callback_query(F.data == "admin_all_appointments")
async def cb_admin_all_appointments(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    await callback.answer()
    appointments = await get_all_future_appointments()
    text = _all_appts_text(appointments, page=0)
    markup = all_appointments_keyboard(appointments, page=0)

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


@router.callback_query(F.data.startswith("apptlist_page_"))
async def cb_admin_apptlist_page(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    from utils.callbacks import parse_callback
    parts = parse_callback(callback.data, "apptlist_page", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    try:
        page = int(parts[0])
    except ValueError:
        await callback.answer()
        return
    appointments = await get_all_future_appointments()
    from utils.panel import edit_panel
    await edit_panel(
        callback.bot, callback.message.chat.id,
        _all_appts_text(appointments, page=page),
        all_appointments_keyboard(appointments, page=page),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_cancel")
async def cb_admin_cancel(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    await callback.answer("Отменено")
    await state.clear()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
        set_panel_msg_id(callback.message.chat.id, callback.message.message_id)
    except TelegramBadRequest:
        pass


@router.message(StateFilter("*"), F.text.regexp(r"^/start(?:\s|$)"))
async def admin_cmd_start(message: Message, state: FSMContext):
    """
    Универсальный escape: /start из любого админ-FSM возвращает на главную.
    Без StateFilter('*') клиентский cmd_start в client.router не дотянется —
    admin_services.msg_addon_add_name (и подобные state-message-хендлеры)
    перехватывают сообщение раньше и записывают «/start» как введённое значение.
    """
    await state.clear()
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    set_reply_kb(message.chat.id, admin_reply_keyboard())
    await message.answer(
        "👑 <b>Панель администратора</b>",
        reply_markup=admin_reply_keyboard(),
        parse_mode="HTML",
    )


@router.message(StateFilter("*"), F.text == "/cancel")
async def cmd_cancel(message: Message, state: FSMContext):
    """/cancel — выйти из FSM в любом состоянии. StateFilter('*') критичен:
    без него хендлер срабатывает только при пустом state, и admin застревает
    в addon_add_name/service_edit_* — текст «/cancel» сохраняется как ввод."""
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
    from handlers.admin_appointments import _calendar_marks_for
    marks = await _calendar_marks_for(now.year, now.month)
    await _nav(message, "🗓 Выберите дату:", calendar_keyboard(now.year, now.month, marks=marks))


@router.message(StateFilter("*"), F.text == "💅 Услуги")
async def msg_services(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    services = await get_services(active_only=False)
    from db import get_active_addon_counts
    addon_counts = await get_active_addon_counts()
    await _nav(message, "💅 Управление услугами:", services_list_keyboard(services, addon_counts=addon_counts))


@router.message(StateFilter("*"), F.text == "📊 Статистика")
async def msg_stats(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    # Локальный импорт: build_stats_payload живёт в admin_stats, который сам
    # импортирует наши хелперы — уровневый импорт сверху создал бы цикл при
    # загрузке роутеров через bot.py (admin → admin_stats → admin при unlucky
    # порядке). Локально безопаснее.
    from handlers.admin_stats import build_stats_payload
    text, kb = await build_stats_payload()
    await _nav(message, text, kb, parse_mode="HTML")


@router.message(StateFilter("*"), F.text == "📒 Все записи")
async def msg_all_appointments(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    appointments = await get_all_future_appointments()
    await _nav(
        message,
        _all_appts_text(appointments, page=0),
        all_appointments_keyboard(appointments, page=0),
    )


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
