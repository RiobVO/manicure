import calendar
from datetime import datetime, timedelta

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from constants import BOOKING_DAYS_AVAILABLE, WEEKDAYS_SHORT_RU
from utils.timezone import now_local
from utils.ui import (
    DIVIDER_SOFT, DIVIDER_WHISPER,
    FLOWER, ARROW_DO, ARROW_SOFT, ARROW_BACK, REPEAT, CLOSE, STAR,
    price as fmt_price, duration as fmt_dur,
    date_soft, date_tiny, date_inline,
    rating_line, hero, meta_row, meta_block, whisper,
    greeting_new, greeting_returning,
    STATUS_MARK, STATUS_WORD,
)

RUSSIAN_WEEKDAYS = {0: "Пн", 1: "Вт", 2: "Ср", 3: "Чт", 4: "Пт", 5: "Сб", 6: "Вс"}
RUSSIAN_MONTHS = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
}

STATUS_EMOJI = {
    "scheduled": "🕐",
    "completed": "✅",
    "no_show": "🚫",
    "cancelled": "❌",
}


# ─── CLIENT KEYBOARDS ────────────────────────────────────────────────────────

def _price_short(price: int) -> str:
    """Цена с пробелом-разделителем тысяч, без «сум». '150 000' вместо '150000'."""
    return f"{price:,}".replace(",", " ")


def category_keyboard() -> InlineKeyboardMarkup:
    """Первый экран записи: выбор ручек/ножек."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❋ ручки", callback_data="cat_hands"),
        InlineKeyboardButton(text="○ ножки", callback_data="cat_feet"),
    ]])


def admin_category_picker() -> InlineKeyboardMarkup:
    """
    Админский выбор категории при создании услуги. Отдельный callback-неймспейс
    (svc_cat_*), чтобы не пересекался с клиентским cat_hands/cat_feet.
    """
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❋ ручки", callback_data="svc_cat_hands"),
        InlineKeyboardButton(text="○ ножки", callback_data="svc_cat_feet"),
    ]])


def services_keyboard(services: list[dict], with_back: bool = False) -> InlineKeyboardMarkup:
    """
    Список услуг с ценами в кнопках: «гель-лак · 150 000».
    with_back=True добавляет «‹ назад» — возврат к выбору категории.
    """
    buttons = []
    for s in services:
        name = s["name"].lower()
        # Срезаем префикс «маникюр/педикюр» — категория уже выбрана пользователем.
        for prefix in ("маникюр с ", "маникюр ", "педикюр с ", "педикюр "):
            if name.startswith(prefix):
                name = name[len(prefix):]
                break
        label = f"{name} · {_price_short(s['price'])}"
        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"service_{s['id']}"
        )])
    if with_back:
        buttons.append([InlineKeyboardButton(text="‹ назад", callback_data="cat_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def dates_keyboard(day_off_weekdays: frozenset[int] = frozenset()) -> InlineKeyboardMarkup:
    # Две колонки, лейбл через date_tiny: «18 апр · пт»
    buttons: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    today = now_local()
    for i in range(BOOKING_DAYS_AVAILABLE):
        day = today + timedelta(days=i)
        if day.weekday() in day_off_weekdays:
            continue  # пропустить выходной по расписанию
        date_str = day.strftime("%Y-%m-%d")
        label = date_tiny(date_str)
        row.append(InlineKeyboardButton(text=label, callback_data=f"date_{date_str}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def times_keyboard(free_slots: list) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for slot in free_slots:
        row.append(InlineKeyboardButton(text=slot, callback_data=f"time_{slot}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def contact_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="поделиться номером", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def addons_keyboard(addons: list[dict], selected_ids: set[int] | None = None) -> InlineKeyboardMarkup:
    """Клавиатура выбора доп. опций. Выбранные помечены акцентом ❀."""
    selected_ids = selected_ids or set()
    buttons = []
    for addon in addons:
        if addon["id"] in selected_ids:
            label = f"{FLOWER} {addon['name']}  +{fmt_price(addon['price'])}"
        else:
            label = f"{addon['name']}  +{fmt_price(addon['price'])}"
        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"addon_{addon['id']}",
        )])
    buttons.append([InlineKeyboardButton(text=f"{ARROW_DO} далее", callback_data="addons_done")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def addon_manage_keyboard(addons: list[dict], service_id: int) -> InlineKeyboardMarkup:
    """Админская клавиатура управления аддонами услуги."""
    buttons = []
    for addon in addons:
        status = "🟢" if addon["is_active"] else "🔴"
        buttons.append([InlineKeyboardButton(
            text=f"{status} {addon['name']} — {addon['price']:,} сум",
            callback_data=f"addon_detail_{addon['id']}",
        )])
    buttons.append([InlineKeyboardButton(text="➕ Добавить опцию", callback_data=f"addon_add_{service_id}")])
    buttons.append([InlineKeyboardButton(text="🔙 К услуге", callback_data=f"svc_detail_{service_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def addon_detail_keyboard(addon: dict) -> InlineKeyboardMarkup:
    """Детали одного аддона — переключить активность или удалить."""
    toggle_text = "🔴 Деактивировать" if addon["is_active"] else "🟢 Активировать"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_text, callback_data=f"addon_toggle_{addon['id']}")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"addon_delete_{addon['id']}")],
        [InlineKeyboardButton(text="🔙 К опциям", callback_data=f"svc_addons_{addon['service_id']}")],
    ])


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"{ARROW_DO} подтвердить", callback_data="confirm_yes"),
        InlineKeyboardButton(text=f"{CLOSE} отмена", callback_data="confirm_no"),
    ]])


CANCEL_REASONS: dict[str, str] = {
    "plans":  "изменились планы",
    "time":   "не устраивает время",
    "master": "нашла другого мастера",
    "other":  "другая причина",
}


def cancel_reason_keyboard(appt_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=label, callback_data=f"cr_{key}_{appt_id}")]
        for key, label in CANCEL_REASONS.items()
    ]
    buttons.append([InlineKeyboardButton(
        text=f"{ARROW_BACK} оставить запись",
        callback_data=f"my_appt_{appt_id}",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def my_appointments_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="мои записи", callback_data="client_my_appointments"),
    ]])


def get_history_pagination_kb(current_page: int, total_pages: int) -> InlineKeyboardMarkup | None:
    """Клавиатура пагинации для истории записей клиента.

    Кнопки ◀/▶ + номер страницы в центре.
    Если total_pages <= 1 — None (пагинация не нужна).
    """
    if total_pages <= 1:
        return None

    row: list[InlineKeyboardButton] = []
    if current_page > 0:
        row.append(InlineKeyboardButton(text="◀", callback_data=f"history_page_{current_page - 1}"))
    row.append(InlineKeyboardButton(
        text=f"{current_page + 1}/{total_pages}",
        callback_data="cal_noop",
    ))
    if current_page < total_pages - 1:
        row.append(InlineKeyboardButton(text="▶", callback_data=f"history_page_{current_page + 1}"))

    return InlineKeyboardMarkup(inline_keyboard=[row])


# ─── MASTER KEYBOARDS ────────────────────────────────────────────────────────

def masters_keyboard(
    masters: list[dict],
    ratings: dict[int, dict] | None = None,
) -> InlineKeyboardMarkup:
    """Клавиатура выбора мастера для клиента."""
    buttons = []
    ratings = ratings or {}
    for m in masters:
        name = m["name"].title()
        if m.get("bio"):
            name += f"  · {m['bio'][:30]}"
        r = ratings.get(m["id"])
        if r and r["avg_rating"]:
            name += f" · {r['avg_rating']}⭐"
        buttons.append([InlineKeyboardButton(
            text=name,
            callback_data=f"master_{m['id']}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_masters_keyboard(masters: list[dict]) -> InlineKeyboardMarkup:
    """Список мастеров в панели администратора."""
    buttons = []
    for m in masters:
        status = "🟢" if m["is_active"] else "🔴"
        buttons.append([InlineKeyboardButton(
            text=f"{status} {m['name']}",
            callback_data=f"master_card_{m['id']}",
        )])
    buttons.append([InlineKeyboardButton(text="➕ Добавить мастера", callback_data="master_add")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def master_card_keyboard(master_id: int, is_active: bool) -> InlineKeyboardMarkup:
    toggle_text = "🔴 Деактивировать" if is_active else "🟢 Активировать"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Имя",    callback_data=f"master_edit_name_{master_id}"),
            InlineKeyboardButton(text="🆔 User ID", callback_data=f"master_edit_uid_{master_id}"),
        ],
        [InlineKeyboardButton(text="📝 Описание",  callback_data=f"master_edit_bio_{master_id}")],
        [InlineKeyboardButton(text="📆 Расписание", callback_data=f"master_sched_{master_id}")],
        [InlineKeyboardButton(text=toggle_text,     callback_data=f"master_toggle_{master_id}")],
        [InlineKeyboardButton(text="🗑 Удалить",    callback_data=f"master_delete_{master_id}")],
        [InlineKeyboardButton(text="🔙 К мастерам", callback_data="admin_masters")],
    ])


def block_master_select_keyboard(masters: list[dict]) -> InlineKeyboardMarkup:
    """Выбор мастера при создании блокировки."""
    buttons = [[InlineKeyboardButton(text="🌐 Все мастера", callback_data="block_master_all")]]
    for m in masters:
        buttons.append([InlineKeyboardButton(
            text=m["name"],
            callback_data=f"block_master_{m['id']}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ─── ADMIN MAIN MENU ─────────────────────────────────────────────────────────

def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📋 Сегодня",      callback_data="admin_today"),
            InlineKeyboardButton(text="📅 Завтра",        callback_data="admin_tomorrow"),
        ],
        [
            InlineKeyboardButton(text="🗓 Календарь",    callback_data="admin_cal"),
            InlineKeyboardButton(text="👥 Клиенты",       callback_data="admin_clients"),
        ],
        [
            InlineKeyboardButton(text="💅 Услуги",        callback_data="admin_services"),
            InlineKeyboardButton(text="👨\u200d🎨 Мастера",   callback_data="admin_masters"),
        ],
        [
            InlineKeyboardButton(text="📊 Статистика",   callback_data="admin_stats"),
            InlineKeyboardButton(text="⚙️ Настройки",    callback_data="admin_settings"),
        ],
        [InlineKeyboardButton(text="🚫 Блокировки",      callback_data="admin_blocks")],
    ])


def review_rating_keyboard(appointment_id: int) -> InlineKeyboardMarkup:
    """
    Клавиатура рейтинга 1-5 без звёздочек — в тон lowercase-эстетики бота.
    Смысл шкалы понятен из контекста вопроса «ну как?».
    """
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=str(n), callback_data=f"rev_rate_{appointment_id}_{n}")
        for n in range(1, 6)
    ]])


def review_comment_keyboard(appointment_id: int) -> InlineKeyboardMarkup:
    """Клавиатура после выбора рейтинга: написать комментарий или пропустить."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✍️ Написать", callback_data=f"rev_comment_{appointment_id}"),
        InlineKeyboardButton(text="Пропустить →", callback_data=f"rev_skip_{appointment_id}"),
    ]])


def client_reply_keyboard() -> ReplyKeyboardMarkup:
    """Постоянная нижняя клавиатура клиента."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="записаться"), KeyboardButton(text="мои записи")],
        ],
        resize_keyboard=True,
    )


def admin_reply_keyboard() -> ReplyKeyboardMarkup:
    """Постоянная нижняя клавиатура мастера."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Сегодня"),    KeyboardButton(text="🗓 Календарь")],
            [KeyboardButton(text="📒 Все записи"), KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="💅 Услуги"),     KeyboardButton(text="👨‍🎨 Мастера")],
            [KeyboardButton(text="👥 Клиенты"),    KeyboardButton(text="🚫 Блокировки")],
            [KeyboardButton(text="📈 Откуда клиенты"), KeyboardButton(text="⚙️ Настройки")],
        ],
        resize_keyboard=True,
    )


def master_reply_keyboard() -> ReplyKeyboardMarkup:
    """Постоянная нижняя клавиатура мастера (кабинет мастера).
    Текст '📋 Сегодня' совпадает с админским — разрулено на уровне
    router-filter: admin-router IsAdminFilter, master-router IsMasterFilter."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Сегодня")],
            [KeyboardButton(text="📅 Мои записи")],
            [KeyboardButton(text="📆 Моё расписание")],
        ],
        resize_keyboard=True,
    )


def admin_cancel_keyboard() -> InlineKeyboardMarkup:
    """Кнопка отмены для FSM-потоков ввода текста."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="↩️ Отмена", callback_data="admin_cancel"),
    ]])


def export_period_keyboard() -> InlineKeyboardMarkup:
    """Выбор периода для экспорта."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Сегодня",   callback_data="export_today")],
        [InlineKeyboardButton(text="📆 Эта неделя", callback_data="export_week")],
        [InlineKeyboardButton(text="🗓 Этот месяц", callback_data="export_month")],
        [InlineKeyboardButton(text="📂 Все записи", callback_data="export_all")],
    ])


def back_to_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 Главное меню", callback_data="admin_home"),
    ]])


# ─── CALENDAR ────────────────────────────────────────────────────────────────

def calendar_keyboard(year: int, month: int) -> InlineKeyboardMarkup:
    buttons = []

    # Навигационная строка
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1

    buttons.append([
        InlineKeyboardButton(text="◀", callback_data=f"cal_prev_{prev_year}_{prev_month}"),
        InlineKeyboardButton(text=f"{RUSSIAN_MONTHS[month]} {year}", callback_data="cal_noop"),
        InlineKeyboardButton(text="▶", callback_data=f"cal_next_{next_year}_{next_month}"),
    ])

    # Заголовок дней недели
    buttons.append([
        InlineKeyboardButton(text=d, callback_data="cal_noop")
        for d in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    ])

    # Дни месяца
    cal = calendar.monthcalendar(year, month)
    for week in cal:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="cal_noop"))
            else:
                row.append(InlineKeyboardButton(
                    text=str(day),
                    callback_data=f"cal_day_{year}_{month}_{day}"
                ))
        buttons.append(row)

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ─── APPOINTMENTS ─────────────────────────────────────────────────────────────

def all_appointments_keyboard(appointments: list[dict]) -> InlineKeyboardMarkup | None:
    """Все предстоящие записи — каждая как кнопка с датой и временем."""
    if not appointments:
        return None
    buttons = []
    for appt in appointments:
        try:
            dt = datetime.strptime(appt["date"], "%Y-%m-%d")
            date_label = f"{dt.day:02d}.{dt.month:02d}"
        except ValueError:
            date_label = appt["date"]
        name_trunc = appt["name"][:20] + ("…" if len(appt["name"]) > 20 else "")
        buttons.append([InlineKeyboardButton(
            text=f"📅 {date_label} {appt['time']} — {name_trunc}",
            callback_data=f"appt_detail_{appt['id']}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def day_view_keyboard(scheduled: list[dict], date_str: str) -> InlineKeyboardMarkup:
    """Только АКТИВНЫЕ (scheduled) записи — каждая как кнопка."""
    buttons = []
    for appt in scheduled:
        name_trunc = appt["name"][:24] + ("…" if len(appt["name"]) > 24 else "")
        buttons.append([InlineKeyboardButton(
            text=f"🕐 {appt['time']} — {name_trunc}",
            callback_data=f"appt_detail_{appt['id']}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None


def appointment_actions_keyboard(
    appt_id: int,
    date_str: str,
    status: str = "scheduled",
    *,
    paid: bool = False,
) -> InlineKeyboardMarkup:
    """
    Кнопки действий зависят от текущего статуса записи:
    - scheduled  → Выполнено | Не пришёл | Отменить | Перенести
    - no_show    → Перенести | Отменить  (статус уже выставлен, смены нет)
    - completed  → только Назад (финальный статус)
    - cancelled  → только Назад (финальный статус)

    `paid=False` + scheduled — добавляем «💰 Пометить оплачено» как резервный
    путь на случай пропущенного webhook (DNS, рестарт, ngrok упал и т.п.).
    """
    buttons = []
    if status == "scheduled":
        buttons.append([
            InlineKeyboardButton(text="✅ Выполнено", callback_data=f"appt_status_{appt_id}_completed"),
            InlineKeyboardButton(text="🚫 Не пришёл", callback_data=f"appt_status_{appt_id}_no_show"),
        ])
        buttons.append([
            InlineKeyboardButton(text="❌ Отменить", callback_data=f"appt_cancel_{appt_id}"),
            InlineKeyboardButton(text="🔄 Перенести", callback_data=f"appt_reschedule_{appt_id}"),
        ])
        if not paid:
            buttons.append([
                InlineKeyboardButton(text="💰 Пометить оплачено", callback_data=f"appt_mark_paid_{appt_id}"),
            ])
    elif status == "no_show":
        # Клиент не пришёл — можно перенести или окончательно отменить
        buttons.append([
            InlineKeyboardButton(text="🔄 Перенести", callback_data=f"appt_reschedule_{appt_id}"),
            InlineKeyboardButton(text="❌ Отменить", callback_data=f"appt_cancel_{appt_id}"),
        ])
    # completed / cancelled → действий нет, только назад

    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"cal_day_back_{date_str}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def cancel_confirm_keyboard(appt_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да, отменить", callback_data=f"appt_cancel_confirm_{appt_id}"),
        InlineKeyboardButton(text="🔙 Назад", callback_data=f"appt_cancel_abort_{appt_id}"),
    ]])


def reschedule_dates_keyboard(appt_id: int) -> InlineKeyboardMarkup:
    buttons = []
    today = now_local()
    for i in range(7):
        day = today + timedelta(days=i)
        weekday_ru = RUSSIAN_WEEKDAYS[day.weekday()]
        label = day.strftime("%d.%m") + f" ({weekday_ru})"
        date_str = day.strftime("%Y-%m-%d")
        buttons.append([InlineKeyboardButton(
            text=label, callback_data=f"rs_date_{appt_id}_{date_str}"
        )])
    buttons.append([InlineKeyboardButton(text="↩️ Отмена", callback_data="admin_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def reschedule_times_keyboard(appt_id: int, date_str: str, free_slots: list) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for slot in free_slots:
        row.append(InlineKeyboardButton(
            text=slot, callback_data=f"rs_time_{appt_id}_{date_str}_{slot}"
        ))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="↩️ Отмена", callback_data="admin_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ─── CLIENTS ──────────────────────────────────────────────────────────────────

def clients_menu_keyboard(clients: list[dict], show_dormant: bool = True) -> InlineKeyboardMarkup:
    buttons = []
    for c in clients:
        last = c.get("last_activity") or "—"
        if last and last != "—":
            try:
                dt = datetime.strptime(last[:10], "%Y-%m-%d")
                last = f"{dt.day:02d}.{dt.month:02d}"
            except ValueError:
                pass
        name_trunc = c["name"][:18] + ("…" if len(c["name"]) > 18 else "")
        completed = c.get("completed_count", 0)
        visits_label = f"{completed}×" if completed else "нов"
        buttons.append([InlineKeyboardButton(
            text=f"👤 {name_trunc} · {visits_label} · {last}",
            callback_data=f"client_card_{c['user_id']}",
        )])

    action_row = [InlineKeyboardButton(text="🔍 Поиск", callback_data="admin_clients_search")]
    if show_dormant:
        action_row.append(
            InlineKeyboardButton(text="🕐 Давно не было", callback_data="admin_clients_dormant")
        )
    buttons.append(action_row)
    buttons.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="admin_home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def client_card_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 К клиентам", callback_data="admin_clients"),
    ]])


# ─── SERVICES ─────────────────────────────────────────────────────────────────

def services_list_keyboard(services: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for s in services:
        status = "🟢" if s["is_active"] else "🔴"
        buttons.append([InlineKeyboardButton(
            text=f"{status} {s['name']} — {s['price']:,} сум",
            callback_data=f"svc_detail_{s['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="➕ Добавить услугу", callback_data="svc_add")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def service_detail_keyboard(service: dict) -> InlineKeyboardMarkup:
    toggle_text = "🔴 Деактивировать" if service["is_active"] else "🟢 Активировать"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Название", callback_data=f"svc_edit_name_{service['id']}"),
            InlineKeyboardButton(text="💰 Цена", callback_data=f"svc_edit_price_{service['id']}"),
        ],
        [
            InlineKeyboardButton(text="⏱ Длительность", callback_data=f"svc_edit_dur_{service['id']}"),
            InlineKeyboardButton(text="📝 Описание", callback_data=f"svc_edit_desc_{service['id']}"),
        ],
        [
            InlineKeyboardButton(text="✨ Доп. опции", callback_data=f"svc_addons_{service['id']}"),
        ],
        [
            InlineKeyboardButton(text=toggle_text, callback_data=f"svc_toggle_{service['id']}"),
        ],
        [
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"svc_delete_{service['id']}"),
        ],
        [InlineKeyboardButton(text="🔙 К услугам", callback_data="admin_services")],
    ])


# ─── SETTINGS ─────────────────────────────────────────────────────────────────

def settings_keyboard(s: dict) -> InlineKeyboardMarkup:
    # Контакт: показываем текущее значение или «не задан», обрезаем если длинный.
    contact_raw = (s.get('salon_contact') or '').strip()
    if contact_raw:
        contact_label = contact_raw if len(contact_raw) <= 28 else contact_raw[:27] + "…"
    else:
        contact_label = "не задан"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"⏱ Шаг слотов: {s.get('slot_step', 30)} мин",
            callback_data="settings_edit_step"
        )],
        [InlineKeyboardButton(text="📅 График по дням", callback_data="sched_weekly")],
        [InlineKeyboardButton(
            text=f"📞 Контакт для клиентов: {contact_label}",
            callback_data="settings_edit_contact"
        )],
        [InlineKeyboardButton(text="📵 Блокировки", callback_data="admin_blocks")],
    ])


def weekly_schedule_keyboard(schedule: dict) -> InlineKeyboardMarkup:
    """Список всех 7 дней с часами работы или пометкой «выходной»."""
    buttons = []
    for wd in range(7):
        row = schedule.get(wd, {})
        day_name = RUSSIAN_WEEKDAYS[wd]
        if row.get("work_start") is None:
            label = f"{day_name}  ❌ выходной"
        else:
            label = f"{day_name}  {row['work_start']:02d}:00 – {row['work_end']:02d}:00"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"sched_day_{wd}")])
    buttons.append([InlineKeyboardButton(text="🔙 Настройки", callback_data="admin_settings")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def master_weekly_schedule_keyboard(
    master_id: int,
    schedule: dict[int, dict],
) -> InlineKeyboardMarkup:
    """Недельная сетка per-master: 7 кнопок по дням + '🔙 К мастеру'.
    schedule: {weekday: {'work_start': int|None, 'work_end': int|None}}.
    Отсутствующий weekday или work_start=None → выходной."""
    buttons = []
    for wd in range(7):
        row = schedule.get(wd) or {}
        if row.get("work_start") is None:
            label = f"{WEEKDAYS_SHORT_RU[wd]} — выходной"
        else:
            label = f"{WEEKDAYS_SHORT_RU[wd]} {row['work_start']:02d}:00–{row['work_end']:02d}:00"
        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"msched_day_{master_id}_{wd}",
        )])
    buttons.append([InlineKeyboardButton(
        text="🔙 К мастеру",
        callback_data=f"master_card_{master_id}",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def master_today_list_keyboard(appointments: list[dict]) -> InlineKeyboardMarkup | None:
    """«📋 Сегодня» для мастера: каждая запись — кликабельная кнопка.
    Callback `mappt_<id>`. None если записей нет (тогда показываем только текст)."""
    if not appointments:
        return None
    buttons = []
    _icon = {"scheduled": "🕐", "completed": "✅", "no_show": "🚫"}
    for a in appointments:
        name_trunc = a["name"][:22] + ("…" if len(a["name"]) > 22 else "")
        icon = _icon.get(a["status"], "·")
        buttons.append([InlineKeyboardButton(
            text=f"{icon} {a['time']} — {name_trunc}",
            callback_data=f"mappt_{a['id']}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def master_upcoming_list_keyboard(appointments: list[dict]) -> InlineKeyboardMarkup | None:
    """«📅 Мои записи» для мастера: кнопки с датой и именем.
    Только scheduled (get_master_appointments_upcoming это гарантирует)."""
    if not appointments:
        return None
    buttons = []
    for a in appointments:
        try:
            dt = datetime.strptime(a["date"], "%Y-%m-%d")
            date_label = f"{dt.day:02d}.{dt.month:02d}"
        except ValueError:
            date_label = a["date"]
        name_trunc = a["name"][:18] + ("…" if len(a["name"]) > 18 else "")
        buttons.append([InlineKeyboardButton(
            text=f"📅 {date_label} {a['time']} — {name_trunc}",
            callback_data=f"mappt_{a['id']}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def master_appt_actions_keyboard(appt_id: int, status: str) -> InlineKeyboardMarkup:
    """Действия мастера над своей записью. Логика та же что в
    admin_appointments::appointment_actions_keyboard — зеркалим, но
    с мастер-namespace'ом callbacks (mappt_status_*, mappt_rs_*, mappt_back_*).
    Финальные статусы (completed/cancelled) — только «🔙 Назад к записям»."""
    buttons = []
    if status == "scheduled":
        buttons.append([
            InlineKeyboardButton(text="✅ Выполнено", callback_data=f"mappt_status_{appt_id}_completed"),
            InlineKeyboardButton(text="🚫 Не пришёл", callback_data=f"mappt_status_{appt_id}_no_show"),
        ])
        buttons.append([
            InlineKeyboardButton(text="❌ Отменить", callback_data=f"mappt_status_{appt_id}_cancelled"),
            InlineKeyboardButton(text="↔ Перенести", callback_data=f"mappt_rs_{appt_id}"),
        ])
    elif status == "no_show":
        # Клиент не пришёл — можно всё ещё перенести или окончательно отменить.
        buttons.append([
            InlineKeyboardButton(text="↔ Перенести", callback_data=f"mappt_rs_{appt_id}"),
            InlineKeyboardButton(text="❌ Отменить", callback_data=f"mappt_status_{appt_id}_cancelled"),
        ])
    # completed / cancelled → действий нет, только назад.
    buttons.append([InlineKeyboardButton(text="🔙 К записям", callback_data="mappt_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def master_rs_dates_keyboard(appt_id: int) -> InlineKeyboardMarkup:
    """7 дат вперёд для переноса. Callback `mappt_rsd_<id>_<YYYY-MM-DD>`."""
    buttons = []
    today = now_local()
    for i in range(7):
        day = today + timedelta(days=i)
        weekday_ru = RUSSIAN_WEEKDAYS[day.weekday()]
        label = day.strftime("%d.%m") + f" ({weekday_ru})"
        date_str = day.strftime("%Y-%m-%d")
        buttons.append([InlineKeyboardButton(
            text=label, callback_data=f"mappt_rsd_{appt_id}_{date_str}",
        )])
    buttons.append([InlineKeyboardButton(
        text="↩ Отмена", callback_data=f"mappt_{appt_id}",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def master_rs_times_keyboard(
    appt_id: int, date_str: str, free_slots: list[str],
) -> InlineKeyboardMarkup:
    """Свободные слоты мастера на выбранной дате, 3 в ряд.
    Callback `mappt_rst_<id>_<YYYY-MM-DD>_<HH:MM>`."""
    buttons = []
    row = []
    for slot in free_slots:
        row.append(InlineKeyboardButton(
            text=slot,
            callback_data=f"mappt_rst_{appt_id}_{date_str}_{slot}",
        ))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(
        text="↩ Отмена", callback_data=f"mappt_{appt_id}",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def master_schedule_menu_keyboard(has_day_offs: bool) -> InlineKeyboardMarkup:
    """Кнопки действий под текстом «📆 Моё расписание» в кабинете мастера.
    «☀ Убрать отгул» показываем только если есть что убирать."""
    buttons = [[InlineKeyboardButton(text="🌙 Поставить отгул", callback_data="mdo_add")]]
    if has_day_offs:
        buttons.append([InlineKeyboardButton(
            text="☀ Убрать отгул", callback_data="mdo_remove_list",
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def master_day_off_dates_keyboard() -> InlineKeyboardMarkup:
    """14 будущих дат — мастер выбирает день для отгула.
    Callback: `mdo_pick_<YYYY-MM-DD>`. Горизонт = BOOKING_DAYS_AVAILABLE,
    чтобы совпадал с клиентским календарём записей."""
    buttons: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    today = now_local()
    for i in range(BOOKING_DAYS_AVAILABLE):
        day = today + timedelta(days=i)
        date_str = day.strftime("%Y-%m-%d")
        row.append(InlineKeyboardButton(
            text=date_tiny(date_str),
            callback_data=f"mdo_pick_{date_str}",
        ))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="🔙 К расписанию", callback_data="mdo_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def master_day_off_remove_keyboard(day_offs: list[dict]) -> InlineKeyboardMarkup:
    """Список будущих отгулов мастера с кнопкой удаления каждого.
    Callback: `mdo_del_<block_id>`."""
    buttons = []
    for d in day_offs:
        buttons.append([InlineKeyboardButton(
            text=f"✕ {date_tiny(d['date'])}",
            callback_data=f"mdo_del_{d['id']}",
        )])
    buttons.append([InlineKeyboardButton(text="🔙 К расписанию", callback_data="mdo_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def master_back_to_schedule_keyboard() -> InlineKeyboardMarkup:
    """Кнопка возврата к расписанию — для экранов warning'а (конфликт, etc)."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 К расписанию", callback_data="mdo_back"),
    ]])


def master_weekday_detail_keyboard(
    master_id: int,
    weekday: int,
    is_day_off: bool,
) -> InlineKeyboardMarkup:
    """Детали weekday для мастера: toggle / edit start / edit end / back."""
    toggle_text = "🟢 Сделать рабочим" if is_day_off else "🔴 Сделать выходным"
    buttons = [
        [InlineKeyboardButton(
            text=toggle_text,
            callback_data=f"msched_toggle_{master_id}_{weekday}",
        )],
    ]
    if not is_day_off:
        buttons.append([
            InlineKeyboardButton(
                text="🕐 Час начала",
                callback_data=f"msched_edit_start_{master_id}_{weekday}",
            ),
            InlineKeyboardButton(
                text="🕕 Час конца",
                callback_data=f"msched_edit_end_{master_id}_{weekday}",
            ),
        ])
    buttons.append([InlineKeyboardButton(
        text="🔙 К расписанию",
        callback_data=f"master_sched_{master_id}",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def weekday_detail_keyboard(weekday: int, is_day_off: bool) -> InlineKeyboardMarkup:
    """Экран редактирования конкретного дня недели."""
    buttons = []
    if not is_day_off:
        buttons.append([
            InlineKeyboardButton(text="🕐 Начало", callback_data=f"sched_edit_start_{weekday}"),
            InlineKeyboardButton(text="🕕 Конец",   callback_data=f"sched_edit_end_{weekday}"),
        ])
    toggle_text = "✅ Сделать рабочим" if is_day_off else "❌ Сделать выходным"
    buttons.append([InlineKeyboardButton(text=toggle_text, callback_data=f"sched_toggle_{weekday}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="sched_weekly")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ─── BLOCKED SLOTS ────────────────────────────────────────────────────────────

def blocks_list_keyboard(blocks: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for b in blocks:
        if b["is_day_off"]:
            label = f"🚫 {b['date']} — весь день"
        else:
            label = f"⏰ {b['date']} {b['time_start']}–{b['time_end']}"
        if b.get("master_name"):
            label += f" ({b['master_name']})"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"block_delete_{b['id']}")])
    buttons.append([InlineKeyboardButton(text="➕ Добавить", callback_data="block_add")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def block_delete_confirm_keyboard(block_id: int) -> InlineKeyboardMarkup:
    """FIX #4: подтверждение перед удалением блокировки."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"block_delete_confirm_{block_id}"),
        InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_blocks"),
    ]])


def block_date_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    today = now_local()
    for i in range(BOOKING_DAYS_AVAILABLE):
        day = today + timedelta(days=i)
        weekday_ru = RUSSIAN_WEEKDAYS[day.weekday()]
        label = day.strftime("%d.%m") + f" ({weekday_ru})"
        date_str = day.strftime("%Y-%m-%d")
        buttons.append([InlineKeyboardButton(
            text=label, callback_data=f"block_date_{date_str}"
        )])
    buttons.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_blocks")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def payment_keyboard(pay_url: str | None, label: str | None = None) -> InlineKeyboardMarkup | None:
    """
    Клавиатура с url-кнопкой на оплату. None если pay_url пустой.
    pay_url формируется в handlers/client.py: либо из PaymentProvider.create_invoice,
    либо (legacy) из PAYMENT_URL-подстановки.

    Намеренно ОДНА кнопка: «Мои записи» внизу в reply-клавиатуре, дублировать
    её инлайном рядом с «Оплатить» плохо — клиент случайно тапал соседнюю
    кнопку, терял доступ к оплате и возврата не было.
    """
    if not pay_url:
        return None
    from config import PAYMENT_LABEL
    text = f"💳 {label or PAYMENT_LABEL}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, url=pay_url)],
    ])


def block_type_keyboard(date_str: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📵 Весь день (выходной)", callback_data=f"block_type_dayoff_{date_str}")],
        [InlineKeyboardButton(text="⏰ Диапазон времени", callback_data=f"block_type_range_{date_str}")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_blocks")],
    ])
