import calendar
from datetime import datetime, timedelta

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from constants import (
    BOOKING_DAYS_AVAILABLE,
    WEEKDAYS_SHORT_RU,
    CATEGORY_KEYS,
    CATEGORY_LABEL_KEYS,
    CATEGORY_ALPHA,
)
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


def category_keyboard(
    lang: str = "ru",
    labels: dict[str, str] | None = None,
) -> InlineKeyboardMarkup:
    """Первый экран записи: выбор категории.

    labels — словарь {category_key → подпись}. Полный набор берётся из
    get_categories_config()['labels']. Если не передан — fallback на дефолты.
    UZ-локализация: если для ключа в labels пусто и язык 'uz', подставляется
    латиничный плейсхолдер по фиксированному маппингу.
    """
    from constants import CATEGORY_DEFAULT_LABELS
    uz_fallback = {
        "hands": "💅 Manikyur",
        "feet": "🦶 Pedikyur",
        "face": "👁 Yuz",
        "depil": "🪒 Depilyatsiya",
        "skincare": "✨ Yuz parvarishi",
        "dental": "🦷 Stomatologiya",
    }
    rows: list[list[InlineKeyboardButton]] = []
    for cat_key, label_key in zip(CATEGORY_KEYS, CATEGORY_LABEL_KEYS):
        text = ""
        if labels:
            text = (labels.get(cat_key) or "").strip()
        if not text:
            text = (
                uz_fallback[cat_key]
                if lang == "uz"
                else CATEGORY_DEFAULT_LABELS[label_key]
            )
        rows.append([InlineKeyboardButton(
            text=text, callback_data=f"cat_{cat_key}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_category_picker(
    labels: dict[str, str] | None = None,
) -> InlineKeyboardMarkup:
    """
    Админский выбор категории при создании услуги. Отдельный callback-неймспейс
    (svc_cat_*), чтобы не пересекался с клиентским cat_*. Подписи симметричны
    клиентскому category_keyboard — admin видит свои же подписи (которые он
    только что мог переименовать в Настройках).

    Шесть кнопок по две в ряд (3 ряда) — компактно и читаемо на мобильных.
    """
    from constants import CATEGORY_DEFAULT_LABELS
    buttons: list[InlineKeyboardButton] = []
    for cat_key, label_key in zip(CATEGORY_KEYS, CATEGORY_LABEL_KEYS):
        text = (labels.get(cat_key) if labels else "") or CATEGORY_DEFAULT_LABELS[label_key]
        buttons.append(InlineKeyboardButton(
            text=text, callback_data=f"svc_cat_{cat_key}",
        ))
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_category_swap_picker(
    service_id: int,
    current_category: str | None,
    labels: dict[str, str] | None = None,
) -> InlineKeyboardMarkup:
    """
    Селектор смены категории у существующей услуги. Текущая категория
    помечена «· сейчас», тап на неё ничего не меняет (можно нажать Назад).
    Callback-формат: svc_setcat_<id>_<key>. Префикс отличный от svc_cat_*
    чтобы не конфликтовать с FSM создания услуги.
    """
    from constants import CATEGORY_DEFAULT_LABELS
    buttons: list[InlineKeyboardButton] = []
    for cat_key, label_key in zip(CATEGORY_KEYS, CATEGORY_LABEL_KEYS):
        text = (labels.get(cat_key) if labels else "") or CATEGORY_DEFAULT_LABELS[label_key]
        if cat_key == current_category:
            text = f"{text} · сейчас"
        buttons.append(InlineKeyboardButton(
            text=text, callback_data=f"svc_setcat_{service_id}_{cat_key}",
        ))
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(
        text="↩ Назад", callback_data=f"svc_detail_{service_id}",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def services_keyboard(
    services: list[dict],
    with_back: bool = False,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    """
    Список услуг с ценами в кнопках: «гель-лак · 150 000».
    with_back=True добавляет «‹ назад» — возврат к выбору категории.
    """
    buttons = []
    # Префиксы, которые срезаем из имени услуги в кнопке: категория уже
    # выбрана пользователем, дублировать «Маникюр» в каждой кнопке не нужно.
    # Для депиляции метод (Воск/Шугаринг) НЕ срезаем — это важная различающая
    # информация: клиент должен видеть «Воск — руки» vs «Шугаринг — руки».
    _prefixes = (
        "маникюр с ", "маникюр ",
        "педикюр с ", "педикюр ",
    )
    for s in services:
        name = s["name"].lower()
        for prefix in _prefixes:
            if name.startswith(prefix):
                name = name[len(prefix):]
                break
        label = f"{name} · {_price_short(s['price'])}"
        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"service_{s['id']}"
        )])
    if with_back:
        back = "‹ orqaga" if lang == "uz" else "‹ назад"
        buttons.append([InlineKeyboardButton(text=back, callback_data="cat_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def dates_keyboard(
    day_off_weekdays: frozenset[int] = frozenset(),
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    # Две колонки, лейбл через date_tiny: «18 апр · пт» / «18 apr · ju»
    buttons: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    today = now_local()
    for i in range(BOOKING_DAYS_AVAILABLE):
        day = today + timedelta(days=i)
        if day.weekday() in day_off_weekdays:
            continue
        date_str = day.strftime("%Y-%m-%d")
        label = date_tiny(date_str, lang)
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


def contact_keyboard(lang: str = "ru") -> ReplyKeyboardMarkup:
    label = "raqamni ulashish" if lang == "uz" else "поделиться номером"
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=label, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def addons_keyboard(
    addons: list[dict],
    selected_ids: set[int] | None = None,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    """Клавиатура выбора доп. опций. Выбранные помечены акцентом ❀."""
    selected_ids = selected_ids or set()
    buttons = []
    for addon in addons:
        if addon["id"] in selected_ids:
            label = f"{FLOWER} {addon['name']}  +{fmt_price(addon['price'], lang)}"
        else:
            label = f"{addon['name']}  +{fmt_price(addon['price'], lang)}"
        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"addon_{addon['id']}",
        )])
    next_label = "→ keyingi" if lang == "uz" else "→ далее"
    buttons.append([InlineKeyboardButton(text=next_label, callback_data="addons_done")])
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


def confirm_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    if lang == "uz":
        yes = "✅ Tasdiqlash"
        no = "❌ Bekor qilish"
    else:
        yes = "✅ Подтвердить"
        no = "❌ Отменить"
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=yes, callback_data="confirm_yes"),
        InlineKeyboardButton(text=no, callback_data="confirm_no"),
    ]])


CANCEL_REASONS: dict[str, str] = {
    "plans":  "изменились планы",
    "time":   "не устраивает время",
    "master": "нашла другого мастера",
    "other":  "другая причина",
}
_CANCEL_REASONS_UZ: dict[str, str] = {
    "plans":  "rejalar o'zgardi",
    "time":   "vaqt mos kelmadi",
    "master": "boshqa ustani topdim",
    "other":  "boshqa sabab",
}


def cancel_reason_keyboard(appt_id: int, lang: str = "ru") -> InlineKeyboardMarkup:
    table = _CANCEL_REASONS_UZ if lang == "uz" else CANCEL_REASONS
    keep = "← yozilishni qoldirish" if lang == "uz" else "← оставить запись"
    buttons = [
        [InlineKeyboardButton(text=label, callback_data=f"cr_{key}_{appt_id}")]
        for key, label in table.items()
    ]
    buttons.append([InlineKeyboardButton(text=keep, callback_data=f"my_appt_{appt_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def my_appointments_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    label = "mening yozilishlarim" if lang == "uz" else "мои записи"
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=label, callback_data="client_my_appointments"),
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


def review_comment_keyboard(appointment_id: int, lang: str = "ru") -> InlineKeyboardMarkup:
    """Клавиатура после выбора рейтинга: написать комментарий или пропустить."""
    if lang == "uz":
        write = "✍️ Yozish"
        skip = "O'tkazib →"
    else:
        write = "✍️ Написать"
        skip = "Пропустить →"
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=write, callback_data=f"rev_comment_{appointment_id}"),
        InlineKeyboardButton(text=skip, callback_data=f"rev_skip_{appointment_id}"),
    ]])


def client_reply_keyboard(lang: str = "ru") -> ReplyKeyboardMarkup:
    """
    Постоянная нижняя клавиатура клиента.

    Надписи зависят от языка, но хендлеры ловят текст через F.text.in_({...}),
    принимая оба варианта — клиент остаётся в живом флоу при смене языка
    (его кнопки из прошлой сессии старого языка всё ещё работают).
    """
    if lang == "uz":
        book_btn = "📅 Yozilish"
        my_btn = "📋 Yozuvlarim"
    else:
        book_btn = "📅 Записаться"
        my_btn = "📋 Мои записи"
    # Переключатель языка — НЕ в reply-клаве (visual noise, клиент меняет
    # язык редко). Доступен через /language и inline-кнопку в «мои записи».
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=book_btn), KeyboardButton(text=my_btn)],
        ],
        resize_keyboard=True,
    )


# Все строки reply-кнопок клиента, по которым фильтруют хендлеры
# (F.text.in_(CLIENT_BTN_BOOK) и т.п.). Старые написания оставлены —
# у клиентов с прошлой сессии кнопки могут быть на них.
CLIENT_BTN_BOOK = frozenset({
    "записаться", "yozilish", "Yozilish",
    "📅 Записаться", "📅 Yozilish",
})
CLIENT_BTN_MY_APPTS = frozenset({
    "мои записи", "mening yozilishlarim", "Mening yozuvlarim",
    "📋 Мои записи", "📋 Yozuvlarim",
})


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
            [KeyboardButton(text="📊 Моя статистика")],
        ],
        resize_keyboard=True,
    )


def master_stats_keyboard(period: str) -> InlineKeyboardMarkup:
    """Inline-переключатель периода ВНУТРИ экрана статистики мастера.
    Текущий период помечен галочкой. Симметрично admin-stats screen,
    но callback_data в неймспейсе mstats_period_* — никаких пересечений
    с admin-роутером."""
    def _btn(p: str, label: str) -> InlineKeyboardButton:
        marker = " ✓" if p == period else ""
        return InlineKeyboardButton(
            text=f"{label}{marker}",
            callback_data=f"mstats_period_{p}",
        )

    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("week", "Неделя"), _btn("month", "Месяц"), _btn("quarter", "3 мес")],
    ])


def admin_cancel_keyboard() -> InlineKeyboardMarkup:
    """Кнопка отмены для FSM-потоков ввода текста."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="↩️ Отмена", callback_data="admin_cancel"),
    ]])


def confirm_delete_keyboard(
    yes_callback: str,
    back_callback: str,
    yes_label: str = "✅ Да, удалить",
    back_label: str = "↩️ Отмена",
) -> InlineKeyboardMarkup:
    """Универсальный confirm-экран для опасных удалений: «Да, удалить» / «Отмена».
    Симметричен block_delete_confirm_keyboard для блокировок — общий стиль
    подтверждения деструктивных действий по всей админке."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=yes_label, callback_data=yes_callback)],
        [InlineKeyboardButton(text=back_label, callback_data=back_callback)],
    ])


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

def calendar_keyboard(
    year: int,
    month: int,
    marks: dict[str, str] | None = None,
) -> InlineKeyboardMarkup:
    """
    Календарь админа. marks — словарь YYYY-MM-DD → префикс ("× " выходной,
    "• " есть записи). Без marks — голые числа (legacy).
    """
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
                date_str = f"{year}-{month:02d}-{day:02d}"
                prefix = marks.get(date_str, "") if marks else ""
                row.append(InlineKeyboardButton(
                    text=f"{prefix}{day}",
                    callback_data=f"cal_day_{year}_{month}_{day}"
                ))
        buttons.append(row)

    # Легенда — только при наличии меток, чтобы не загромождать пустой месяц
    if marks:
        buttons.append([InlineKeyboardButton(
            text="• есть записи   × выходной",
            callback_data="cal_noop",
        )])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ─── APPOINTMENTS ─────────────────────────────────────────────────────────────

APPTS_PER_PAGE = 10


def all_appointments_keyboard(
    appointments: list[dict],
    page: int = 0,
    per_page: int = APPTS_PER_PAGE,
) -> InlineKeyboardMarkup | None:
    """Все предстоящие записи — пагинация по 10 на страницу. Кнопка-запись
    тапается → карточка записи. Стрелки скрываются на крайних страницах."""
    if not appointments:
        return None
    total = len(appointments)
    per_page = max(1, per_page)
    total_pages = (total + per_page - 1) // per_page
    page = max(0, min(page, total_pages - 1))
    start = page * per_page

    buttons: list[list[InlineKeyboardButton]] = []
    for appt in appointments[start:start + per_page]:
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

    if total_pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀", callback_data=f"apptlist_page_{page - 1}"))
        nav.append(InlineKeyboardButton(
            text=f"{page + 1}/{total_pages}",
            callback_data="cal_noop",
        ))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="▶", callback_data=f"apptlist_page_{page + 1}"))
        buttons.append(nav)

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def day_view_keyboard(scheduled: list[dict], date_str: str) -> InlineKeyboardMarkup:
    """
    Клавиатура дневного вида: список активных записей + ➕ «Записать клиента»
    в шапке. Кнопка ➕ есть всегда — даже на пустом дне, чтобы владелица
    могла записать клиента на любой день одним тапом.

    Внизу — «🚫 Сделать выходным» (только для today/future): тап = блокировка
    дня без захода в «📵 Блокировки → добавить → выбор даты из 14 дней».
    Прошлые дни не показывают кнопку — закрывать вчера бессмысленно.
    """
    buttons: list[list[InlineKeyboardButton]] = []
    buttons.append([InlineKeyboardButton(
        text="➕ Записать клиента",
        callback_data=f"qadd_start_{date_str}",
    )])
    for appt in scheduled:
        name_trunc = appt["name"][:24] + ("…" if len(appt["name"]) > 24 else "")
        buttons.append([InlineKeyboardButton(
            text=f"🕐 {appt['time']} — {name_trunc}",
            callback_data=f"appt_detail_{appt['id']}",
        )])

    today_str = now_local().strftime("%Y-%m-%d")
    if date_str > today_str:
        # Только строго будущие дни. На «Сегодня» закрывать смысла нет —
        # рабочий день идёт, записи активны; админ всё равно их не успеет
        # перенести, и UX здесь ложноположительный.
        buttons.append([InlineKeyboardButton(
            text="🚫 Сделать выходным",
            callback_data=f"caldayoff_{date_str}",
        )])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def caldayoff_master_picker_keyboard(date_str: str, masters: list[dict]) -> InlineKeyboardMarkup:
    """Выбор мастера для блокировки дня прямо из календаря.

    Не переиспользую block_master_select_keyboard — у него callback'и
    `block_master_*`, которые ловит FSM-хендлер cb_block_master (требует
    state). Тут нужен прямой блок без FSM, поэтому свои callback'и
    с датой внутри: `caldayoff_pick_<date>_<id|all>`.
    """
    buttons = [[InlineKeyboardButton(
        text="🌐 Все мастера",
        callback_data=f"caldayoff_pick_{date_str}_all",
    )]]
    for m in masters:
        buttons.append([InlineKeyboardButton(
            text=m["name"],
            callback_data=f"caldayoff_pick_{date_str}_{m['id']}",
        )])
    buttons.append([InlineKeyboardButton(
        text="↩️ Отмена",
        callback_data=f"cal_day_back_{date_str}",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ─── QUICK-ADD: ручная запись клиента из day-view ───────────────────────────

def qadd_skip_phone_keyboard(date_str: str) -> InlineKeyboardMarkup:
    """Шаг «телефон»: разрешаем пропустить — для звонков «впишите быстро»
    телефон не критичен; напоминания не уйдут, но запись создастся."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Пропустить", callback_data="qadd_skip_phone")],
        [InlineKeyboardButton(text="↩️ Отмена", callback_data=f"qadd_cancel_{date_str}")],
    ])


def qadd_services_keyboard(services: list[dict], date_str: str) -> InlineKeyboardMarkup:
    """Шаг «услуга»: показываем все активные с ценой и длительностью.
    Аддоны в quick-add не выбираются (упрощаем — это редкий сценарий
    у телефонной записи). Если нужны — добавит сама в карточке записи."""
    rows = []
    for svc in services:
        label = f"{svc['name']} · {_price_short(svc['price'])} · {svc['duration']}мин"
        rows.append([InlineKeyboardButton(
            text=label,
            callback_data=f"qadd_svc_{svc['id']}",
        )])
    rows.append([InlineKeyboardButton(text="↩️ Отмена", callback_data=f"qadd_cancel_{date_str}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def qadd_masters_keyboard(masters: list[dict], date_str: str) -> InlineKeyboardMarkup:
    """Шаг «мастер»: список активных. Опция «Любой свободный» — записать
    без привязки (master_id=NULL), как в клиентском flow. Полезно когда
    владелица не помнит у кого окно или клиент не привязан к конкретной."""
    rows = []
    row: list[InlineKeyboardButton] = []
    for m in masters:
        row.append(InlineKeyboardButton(
            text=m["name"],
            callback_data=f"qadd_master_{m['id']}",
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(
        text="👥 Любой свободный",
        callback_data="qadd_master_any",
    )])
    rows.append([InlineKeyboardButton(text="↩️ Отмена", callback_data=f"qadd_cancel_{date_str}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def qadd_times_keyboard(free_slots: list[str], date_str: str) -> InlineKeyboardMarkup:
    """Шаг «время»: 3 кнопки в ряду из свободных слотов. Симметрично
    клиентскому times_keyboard — единый стиль выбора времени."""
    rows = []
    row: list[InlineKeyboardButton] = []
    for slot in free_slots:
        row.append(InlineKeyboardButton(text=slot, callback_data=f"qadd_time_{slot}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="↩️ Отмена", callback_data=f"qadd_cancel_{date_str}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def qadd_confirm_keyboard(date_str: str) -> InlineKeyboardMarkup:
    """Финальный шаг: «✅ Записать» / «↩️ Отмена»."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Записать", callback_data="qadd_confirm")],
        [InlineKeyboardButton(text="↩️ Отмена", callback_data=f"qadd_cancel_{date_str}")],
    ])


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

SERVICES_PER_PAGE = 8


def services_list_keyboard(
    services: list[dict],
    page: int = 0,
    per_page: int = SERVICES_PER_PAGE,
    addon_counts: dict[int, int] | None = None,
) -> InlineKeyboardMarkup:
    """
    Пагинированный список услуг в админке. ~8 на страницу — без скролла на
    стандартном экране телефона. Footer: «◀» «N/M» «▶» (стрелки на крайних
    страницах скрыты, счётчик не кликабельный — cal_noop).

    addon_counts: {service_id: число активных аддонов}. Если передан и >0 —
    к тексту дописывается «· ➕N». Без него — без бейджа (legacy).
    """
    buttons: list[list[InlineKeyboardButton]] = []
    total = len(services)
    if total > 0:
        per_page = max(1, per_page)
        total_pages = (total + per_page - 1) // per_page
        page = max(0, min(page, total_pages - 1))
        start = page * per_page
        for s in services[start:start + per_page]:
            status = "🟢" if s["is_active"] else "🔴"
            label = f"{status} {s['name']} — {s['price']:,} сум"
            if addon_counts:
                n = addon_counts.get(s["id"], 0)
                if n > 0:
                    label += f" · ➕{n}"
            # Активная услуга с price=0 видна клиенту бесплатно — почти всегда
            # это забытый placeholder («Лицо», «Брови»). Флажок ⚠️ заметен
            # в списке, в карточке (svc_detail) Сабина увидит подробности.
            if s["is_active"] and s["price"] == 0:
                label += " ⚠️"
            buttons.append([InlineKeyboardButton(
                text=label,
                callback_data=f"svc_detail_{s['id']}",
            )])
        if total_pages > 1:
            nav: list[InlineKeyboardButton] = []
            if page > 0:
                nav.append(InlineKeyboardButton(text="◀", callback_data=f"svc_page_{page - 1}"))
            nav.append(InlineKeyboardButton(
                text=f"{page + 1}/{total_pages}",
                callback_data="cal_noop",
            ))
            if page < total_pages - 1:
                nav.append(InlineKeyboardButton(text="▶", callback_data=f"svc_page_{page + 1}"))
            buttons.append(nav)

    buttons.append([InlineKeyboardButton(text="➕ Добавить услугу", callback_data="svc_add")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def service_detail_keyboard(
    service: dict,
    cat_label: str | None = None,
) -> InlineKeyboardMarkup:
    """
    Карточка услуги в админке. Если cat_label передан — показываем кнопку
    «🏷 {label}» для перехода между категориями (toggle hands↔feet). В
    плоском режиме (use_categories=false) caller передаёт None — кнопка
    скрывается, потому что категория там значения не имеет.
    """
    toggle_text = "🔴 Деактивировать" if service["is_active"] else "🟢 Активировать"
    rows = [
        [
            InlineKeyboardButton(text="✏️ Название", callback_data=f"svc_edit_name_{service['id']}"),
            InlineKeyboardButton(text="💰 Цена", callback_data=f"svc_edit_price_{service['id']}"),
        ],
        [
            InlineKeyboardButton(text="⏱ Длительность", callback_data=f"svc_edit_dur_{service['id']}"),
            InlineKeyboardButton(text="📝 Описание", callback_data=f"svc_edit_desc_{service['id']}"),
        ],
    ]
    if cat_label:
        # С 6 категориями toggle бессмысленен — открываем полноценный селектор.
        rows.append([
            InlineKeyboardButton(
                text=f"🏷 Категория: {cat_label}",
                callback_data=f"svc_setcat_open_{service['id']}",
            ),
        ])
    rows.extend([
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
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ─── SETTINGS ─────────────────────────────────────────────────────────────────

def settings_keyboard(s: dict) -> InlineKeyboardMarkup:
    def _short(raw: str, placeholder: str = "не задано") -> str:
        raw = (raw or "").strip()
        if not raw:
            return placeholder
        return raw if len(raw) <= 28 else raw[:27] + "…"

    contact_label = _short(s.get("salon_contact") or "", placeholder="не задан")
    name_label = _short(s.get("salon_name") or "")
    # Категории: 6 штук — выводим компактно «вкл · 6 кат.», в плоском режиме
    # «выкл · плоский список». Полный список редактируется на отдельном
    # экране (categories_menu_keyboard).
    use_cats = (s.get("use_categories") or "1").strip() != "0"
    if use_cats:
        cat_button = f"🏷 Категории: вкл · {len(CATEGORY_KEYS)} шт."
    else:
        cat_button = "🏷 Категории: выкл · плоский список"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"⏱ Шаг слотов: {s.get('slot_step', 30)} мин",
            callback_data="settings_edit_step"
        )],
        [InlineKeyboardButton(text="📅 График по дням", callback_data="sched_weekly")],
        [InlineKeyboardButton(
            text=cat_button,
            callback_data="settings_categories_menu",
        )],
        [InlineKeyboardButton(
            text=f"🏷 Название салона: {name_label}",
            callback_data="settings_edit_name"
        )],
        [InlineKeyboardButton(
            text=f"📞 Контакт для клиентов: {contact_label}",
            callback_data="settings_edit_contact"
        )],
        [InlineKeyboardButton(text="📵 Блокировки", callback_data="admin_blocks")],
    ])


def categories_menu_keyboard(
    use_categories: bool,
    labels: dict[str, str] | None = None,
) -> InlineKeyboardMarkup:
    """Экран «🏷 Категории услуг»: переключатель режима + редактирование меток.
    Кнопки редактирования меток скрыты в плоском режиме — там подписи некуда
    применять. labels — словарь {key→текущая подпись} для отображения справа
    от буквы категории; если не передан, выводим только букву."""
    from constants import CATEGORY_DEFAULT_LABELS
    rows: list[list[InlineKeyboardButton]] = []
    toggle_label = (
        "🔄 Переключить на «плоский список»"
        if use_categories else
        "🔄 Переключить на «6 категорий»"
    )
    rows.append([InlineKeyboardButton(
        text=toggle_label,
        callback_data="settings_categories_toggle",
    )])
    if use_categories:
        # Кнопка на каждую категорию: «✏ А · 💅 Маникюр» — букву даём для
        # консистентности с FSM-states (cat_a_label..cat_f_label), подпись
        # рядом чтобы не нужно было лезть в каждую для проверки.
        for cat_key, label_key, alpha in zip(
            CATEGORY_KEYS, CATEGORY_LABEL_KEYS, CATEGORY_ALPHA
        ):
            current = ""
            if labels:
                current = (labels.get(cat_key) or "").strip()
            if not current:
                current = CATEGORY_DEFAULT_LABELS[label_key]
            short = current if len(current) <= 24 else current[:23] + "…"
            slot_letter = label_key.split("_")[1]  # 'a'..'f'
            rows.append([InlineKeyboardButton(
                text=f"✏ {alpha} · {short}",
                callback_data=f"settings_edit_cat_{slot_letter}",
            )])
    rows.append([InlineKeyboardButton(text="↩ К настройкам", callback_data="admin_settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
    if label:
        text = f"💳 {label}"
    else:
        from config import PAYMENT_LABEL
        text = f"💳 {PAYMENT_LABEL}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, url=pay_url)],
    ])


def block_type_keyboard(date_str: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📵 Весь день (выходной)", callback_data=f"block_type_dayoff_{date_str}")],
        [InlineKeyboardButton(text="⏰ Диапазон времени", callback_data=f"block_type_range_{date_str}")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_blocks")],
    ])
