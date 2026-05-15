"""
Дизайн-система клиентского UX · Jardin Blanc.

Тон: строчные буквы, Cormorant-italic через HTML <b><i>, ботанический акцент ❀
максимум один на экран. Без капса, без восклицательных, без эмодзи-декора.

Phase 3 v.4: функции принимают lang ('ru' | 'uz'). По умолчанию 'ru' —
backward compat с местами вызова, которые ещё не параметризованы.
"""

import html as _html
from datetime import datetime


# ─── HTML ESCAPE ─────────────────────────────────────────────────────────────
# Применять к user-controlled строкам (имя клиента, телефон, описание услуги,
# bio мастера и т.п.) перед подстановкой в сообщения с parse_mode="HTML".
# Без этого одно имя вида "Катя <3" ломает send_message TelegramBadRequest'ом.

def h(s: str | None) -> str:
    """HTML-escape для подстановки в parse_mode=HTML. None → пустая строка."""
    if s is None:
        return ""
    return _html.escape(str(s), quote=False)


# ─── РАЗДЕЛИТЕЛИ ─────────────────────────────────────────────────────────────

DIVIDER_SOFT    = "· · · · · · · · · · · · ·"
DIVIDER_WHISPER = "· · ·"
DIVIDER_LINE    = "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯"

# ─── АКЦЕНТ-СИМВОЛЫ ──────────────────────────────────────────────────────────

FLOWER  = "❀"   # декоративный акцент, одного на экран достаточно
PETAL   = "✿"   # альтернативный, для карточек мастера
STAR    = "✦"   # только для подтверждения записи и особых моментов

ARROW_DO   = "→"
ARROW_SOFT = "›"
ARROW_BACK = "←"
REPEAT     = "↻"
CLOSE      = "✕"


# ─── ДАТЫ: месяцы и дни недели ───────────────────────────────────────────────

# Родительный падеж («18 апреля»).
_MONTHS_GEN_RU = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
# Узбекский (латиница, официальный алфавит).
_MONTHS_UZ = (
    "yanvar", "fevral", "mart", "aprel", "may", "iyun",
    "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr",
)
_MONTHS_SHORT_RU = (
    "янв", "фев", "мар", "апр", "май", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек",
)
_MONTHS_SHORT_UZ = (
    "yan", "fev", "mar", "apr", "may", "iyn",
    "iyl", "avg", "sen", "okt", "noy", "dek",
)

_WEEKDAYS_FULL_RU = (
    "понедельник", "вторник", "среда", "четверг",
    "пятница", "суббота", "воскресенье",
)
_WEEKDAYS_FULL_UZ = (
    "dushanba", "seshanba", "chorshanba", "payshanba",
    "juma", "shanba", "yakshanba",
)
_WEEKDAYS_SHORT_RU = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
_WEEKDAYS_SHORT_UZ = ("du", "se", "ch", "pa", "ju", "sh", "ya")


# ─── ФОРМАТТЕРЫ ──────────────────────────────────────────────────────────────

def price(amount: int, lang: str = "ru") -> str:
    """250000 → '250 000 сум' / '250 000 so'm'."""
    num = f"{amount:,}".replace(",", "\u202f")
    suffix = "so'm" if lang == "uz" else "сум"
    return f"{num} {suffix}"


def price_plain(amount: int) -> str:
    """Без валюты: '250 000'. Язык-независимо."""
    return f"{amount:,}".replace(",", "\u202f")


def duration(minutes: int, lang: str = "ru") -> str:
    """45 → '45 мин' / '45 daqiqa', 90 → '1 ч 30 мин' / '1 soat 30 daqiqa'."""
    if lang == "uz":
        _min = "daqiqa"
        _hour = "soat"
    else:
        _min = "мин"
        _hour = "ч"
    if minutes < 60:
        return f"{minutes} {_min}"
    hrs, mins = divmod(minutes, 60)
    if mins == 0:
        return f"{hrs} {_hour}"
    return f"{hrs} {_hour} {mins} {_min}"


def date_soft(date_str: str, lang: str = "ru") -> str:
    """'2026-04-18' → 'пятница, 18 апреля' / 'juma, 18 aprel'."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        if lang == "uz":
            wd = _WEEKDAYS_FULL_UZ[dt.weekday()]
            mo = _MONTHS_UZ[dt.month - 1]
        else:
            wd = _WEEKDAYS_FULL_RU[dt.weekday()]
            mo = _MONTHS_GEN_RU[dt.month - 1]
        return f"{wd}, {dt.day} {mo}"
    except ValueError:
        return date_str


def date_tiny(date_str: str, lang: str = "ru") -> str:
    """'2026-04-18' → '18 апр · пт' / '18 apr · ju'."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        if lang == "uz":
            mo = _MONTHS_SHORT_UZ[dt.month - 1]
            wd = _WEEKDAYS_SHORT_UZ[dt.weekday()]
        else:
            mo = _MONTHS_SHORT_RU[dt.month - 1]
            wd = _WEEKDAYS_SHORT_RU[dt.weekday()]
        return f"{dt.day} {mo} · {wd}"
    except ValueError:
        return date_str


def date_inline(date_str: str, lang: str = "ru") -> str:
    """'2026-04-18' → '18 апреля' / '18 aprel'."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        mo = _MONTHS_UZ[dt.month - 1] if lang == "uz" else _MONTHS_GEN_RU[dt.month - 1]
        return f"{dt.day} {mo}"
    except ValueError:
        return date_str


def days_ago_phrase(days: int, lang: str = "ru") -> str:
    """
    N дней назад → человеческая фраза. 0 → 'сегодня'/'bugun', 1 → 'вчера'/'kecha',
    дальше русская плюрализация или универсальная uz-форма 'N kun oldin'.
    """
    if lang == "uz":
        if days <= 0:
            return "bugun"
        if days == 1:
            return "kecha"
        if days < 7:
            return f"{days} kun oldin"
        if days < 30:
            return f"{days // 7} hafta oldin"
        if days < 365:
            return f"{days // 30} oy oldin"
        return f"{days // 365} yil oldin"
    # ru
    if days <= 0:
        return "сегодня"
    if days == 1:
        return "вчера"
    if days < 7:
        return f"прошло {days} {_plural_ru(days, 'день', 'дня', 'дней')}"
    if days < 30:
        w = days // 7
        return f"прошло {w} {_plural_ru(w, 'неделя', 'недели', 'недель')}"
    if days < 365:
        m = days // 30
        return f"прошло {m} {_plural_ru(m, 'месяц', 'месяца', 'месяцев')}"
    y = days // 365
    return f"прошло {y} {_plural_ru(y, 'год', 'года', 'лет')}"


def _plural_ru(n: int, one: str, few: str, many: str) -> str:
    n = abs(n) % 100
    if 11 <= n <= 14:
        return many
    n %= 10
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


# Бэкап-имя для импортов, которые уже ссылаются на _plural (старый public API).
_plural = _plural_ru


def rating_line(avg: float | None, count: int) -> str:
    """Звёздочки ботаникой: ❀❀❀❀❀  4.9 · 142. Если нет — пустая строка.
    Язык-независимо (только числа + символы)."""
    if not avg or not count:
        return ""
    filled = round(avg)
    stars = FLOWER * filled + "·" * (5 - filled)
    return f"<i>{stars}  {avg} · {count}</i>"


# ─── БЛОКИ СООБЩЕНИЙ ─────────────────────────────────────────────────────────

def hero(title: str, subtitle: str | None = None) -> str:
    """Заголовок экрана. Язык-независимо (вызывающий передаёт уже переведённую строку)."""
    out = f"<b><i>{title}</i></b>"
    if subtitle:
        out += f"\n{DIVIDER_SOFT}\n<i>{subtitle}</i>"
    return out


def meta_row(label: str, value: str) -> str:
    """Одна строка «label    · value» — визуальная таблица."""
    return f"<i>{label}</i>  ·  <code>{value}</code>"


def meta_block(pairs: list[tuple[str, str]]) -> str:
    """Несколько meta-строк подряд."""
    return "\n".join(meta_row(l, v) for l, v in pairs)


def whisper(text: str) -> str:
    """Малозаметная подпись курсивом с серым тоном через i."""
    return f"<i>{text}</i>"


def accent(symbol: str = FLOWER) -> str:
    """Одиночный акцент-символ по центру, отдельной строкой."""
    return f"\n{symbol}\n"


# ─── ПРИВЕТСТВИЯ ─────────────────────────────────────────────────────────────

def greeting_new(lang: str = "ru") -> str:
    """Приветствие нового клиента."""
    if lang == "uz":
        return (
            "Salom! Men Sabinaning yordamchisiman. U go'zal tirnoqlar "
            "ustida sehr ko'rsatayotgan bir vaqtda, men sizga navbatga "
            "yozilishda yordam beraman ✨\n\n"
            "Bo'sh vaqt topamiz, darhol yozib qo'yaman va eslatma yuboraman.\n\n"
            "Vaqtni tanlaymizmi? 👇"
        )
    return (
        "Привет! Я бот Сабины. Пока она пилит красивые ноготочки, "
        "я помогаю с записью ✨\n\n"
        "Помогу найти свободное окно, моментально тебя запишу и пришлю "
        "напоминалку, чтобы визит не вылетел из головы.\n\n"
        "Посмотрим, что там по времени? 👇"
    )


def greeting_returning(
    name: str,
    days_ago: int,
    service: str,
    master: str | None,
    lang: str = "ru",
) -> str:
    """Приветствие возвращающегося клиента. Коротко, без сантиментов."""
    if lang == "uz":
        if days_ago == 0:
            when = "bugun"
        elif days_ago == 1:
            when = "kecha"
        else:
            when = days_ago_phrase(days_ago, lang=lang)
        master_line = f" · {h(master.title())}" if master else ""
        return (
            f"{FLOWER}\n\n"
            f"<b><i>{h(name)}.</i></b>\n\n"
            f"<i>o'tgan safar — {h(service.lower())}{master_line}.</i>\n"
            f"<i>{when}.</i>"
        )

    # ru
    if days_ago == 0:
        when = "сегодня"
    elif days_ago == 1:
        when = "вчера"
    else:
        when = days_ago_phrase(days_ago).replace("прошло ", "")
    master_line = f" · {h(master.title())}" if master else ""
    return (
        f"{FLOWER}\n\n"
        f"<b><i>{h(name)}.</i></b>\n\n"
        f"<i>прошлый раз — {h(service.lower())}{master_line}.</i>\n"
        f"<i>{when}.</i>"
    )


def booking_done_hero(name: str, lang: str = "ru") -> str:
    """Первое сообщение после успешной записи — акцент."""
    if lang == "uz":
        return f"{STAR}\n\n<b><i>{h(name)}, tayyor.</i></b>\n<i>siz yozildingiz.</i>"
    return f"{STAR}\n\n<b><i>{h(name)}, всё.</i></b>\n<i>ты записана.</i>"


def booking_reminder_note(lang: str = "ru") -> str:
    """Третье сообщение после подтверждения — напоминание."""
    if lang == "uz":
        return (
            f"<i>bir kun oldin</i>\n"
            f"<i>va tashrifingizdan ikki soat oldin eslataman.</i>\n\n"
            f"<i>ko'rishguncha ✧</i>"
        )
    return (
        f"<i>напомню за сутки</i>\n"
        f"<i>и за два часа до визита.</i>\n\n"
        f"<i>до встречи ✧</i>"
    )


# ─── ТОНКИЕ TEXTUAL-ИКОНКИ ДЛЯ СТАТУСОВ ──────────────────────────────────────
# Маркеры язык-независимые. Словесные статусы — локализованы.

STATUS_MARK = {
    "scheduled": "●",   # ждёт (яркая точка)
    "completed": "✓",   # состоялся (галка)
    "no_show":   "—",   # не пришли (тире)
    "cancelled": "✕",   # отменён (крестик)
}

STATUS_WORD_RU = {
    "scheduled": "ждёт",
    "completed": "состоялся",
    "no_show":   "не пришли",
    "cancelled": "отменён",
}
STATUS_WORD_UZ = {
    "scheduled": "kutmoqda",
    "completed": "bo'lib o'tdi",
    "no_show":   "kelmadi",
    "cancelled": "bekor qilindi",
}
# Backward-compat: старые вызовы без lang → русские.
STATUS_WORD = STATUS_WORD_RU


def status_word(status: str, lang: str = "ru") -> str:
    """Локализованное словесное описание статуса записи."""
    table = STATUS_WORD_UZ if lang == "uz" else STATUS_WORD_RU
    return table.get(status, status)
