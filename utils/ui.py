"""
Дизайн-система клиентского UX · Jardin Blanc.

Тон: строчные буквы, Cormorant-italic через HTML <b><i>, ботанический акцент ❀
максимум один на экран. Без капса, без восклицательных, без эмодзи-декора.

Разделители:
  SOFT    · · · · · · · · · · · · ·     основной между секциями
  WHISPER · · ·                         тихий внутри блока
  LINE    ⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯     структурный (редко)

Функциональные символы (всегда монохром, без цвета):
  ↻  повторить / перенести
  →  действие-переход
  ›  вторичный переход
  ✕  отмена / закрыть
  ←  возврат
  ❀  ботанический акцент (декор, не функция)
  ✦  открытие/успех (редко, для вау-моментов)

Всё форматирование — Telegram HTML (<b>, <i>, <code>).
"""

from datetime import datetime

from constants import MONTHS_RU, WEEKDAYS_SHORT_RU

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

# ─── МЕСЯЦЫ В РОДИТЕЛЬНОМ ПАДЕЖЕ (для «18 апреля») ──────────────────────────

MONTHS_GENITIVE = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]

WEEKDAYS_FULL_LOWER = [
    "понедельник", "вторник", "среда", "четверг",
    "пятница", "суббота", "воскресенье",
]


# ─── ФОРМАТТЕРЫ ──────────────────────────────────────────────────────────────

def price(amount: int) -> str:
    """250000 → '250 000 сум'. Неразрывный пробел между разрядами."""
    return f"{amount:,} сум".replace(",", "\u202f")


def price_plain(amount: int) -> str:
    """Без валюты: '250 000'."""
    return f"{amount:,}".replace(",", "\u202f")


def duration(minutes: int) -> str:
    """45 → '45 мин', 90 → '1 ч 30 мин'."""
    if minutes < 60:
        return f"{minutes} мин"
    h, m = divmod(minutes, 60)
    if m == 0:
        return f"{h} ч"
    return f"{h} ч {m} мин"


def date_soft(date_str: str) -> str:
    """'2026-04-18' → 'пятница, 18 апреля'."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{WEEKDAYS_FULL_LOWER[dt.weekday()]}, {dt.day} {MONTHS_GENITIVE[dt.month - 1]}"
    except ValueError:
        return date_str


def date_tiny(date_str: str) -> str:
    """'2026-04-18' → '18 апр · пт'. Для списков и кнопок."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        month_short = MONTHS_RU[dt.month - 1][:3].lower()
        return f"{dt.day} {month_short} · {WEEKDAYS_SHORT_RU[dt.weekday()].lower()}"
    except ValueError:
        return date_str


def date_inline(date_str: str) -> str:
    """'2026-04-18' → '18 апреля'. Для inline-вставок."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.day} {MONTHS_GENITIVE[dt.month - 1]}"
    except ValueError:
        return date_str


def days_ago_phrase(days: int) -> str:
    """N дней назад → человеческая фраза. 1→'вчера', 0→'сегодня', ..."""
    if days <= 0:
        return "сегодня"
    if days == 1:
        return "вчера"
    if days < 7:
        return f"прошло {days} {_plural(days, 'день', 'дня', 'дней')}"
    if days < 30:
        w = days // 7
        return f"прошло {w} {_plural(w, 'неделя', 'недели', 'недель')}"
    if days < 365:
        m = days // 30
        return f"прошло {m} {_plural(m, 'месяц', 'месяца', 'месяцев')}"
    y = days // 365
    return f"прошло {y} {_plural(y, 'год', 'года', 'лет')}"


def _plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n) % 100
    if 11 <= n <= 14:
        return many
    n %= 10
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


def rating_line(avg: float | None, count: int) -> str:
    """Звёздочки ботаникой: ❀❀❀❀❀  4.9 · 142. Если нет — пустая строка."""
    if not avg or not count:
        return ""
    filled = round(avg)
    stars = FLOWER * filled + "·" * (5 - filled)
    return f"<i>{stars}  {avg} · {count}</i>"


# ─── БЛОКИ СООБЩЕНИЙ ─────────────────────────────────────────────────────────

def hero(title: str, subtitle: str | None = None) -> str:
    """
    Заголовок экрана: жирный курсив + опциональная подпись.
        <b><i>маникюр классический</i></b>
        · · · · · · · · · · · · ·
        <i>форма, кутикула, база</i>
    """
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

def greeting_new() -> str:
    """Приветствие нового клиента."""
    return (
        f"{FLOWER}\n\n"
        f"<b><i>запись к мастеру.</i></b>\n\n"
        f"<i>выбери услугу.</i>"
    )


def greeting_returning(name: str, days_ago: int, service: str, master: str | None) -> str:
    """Приветствие возвращающегося клиента. Коротко, без сантиментов."""
    if days_ago == 0:
        when = "сегодня"
    elif days_ago == 1:
        when = "вчера"
    else:
        when = days_ago_phrase(days_ago).replace("прошло ", "")

    master_line = f" · {master.title()}" if master else ""
    return (
        f"{FLOWER}\n\n"
        f"<b><i>{name}.</i></b>\n\n"
        f"<i>прошлый раз — {service.lower()}{master_line}.</i>\n"
        f"<i>{when}.</i>"
    )


def booking_done_hero(name: str) -> str:
    """Первое сообщение после успешной записи — акцент."""
    return f"{STAR}\n\n<b><i>{name}, всё.</i></b>\n<i>ты записана.</i>"


def booking_reminder_note() -> str:
    """Третье сообщение после подтверждения — напоминание."""
    return (
        f"<i>напомню за сутки</i>\n"
        f"<i>и за два часа до визита.</i>"
    )


# ─── ТОНКИЕ TEXTUAL-ИКОНКИ ДЛЯ СТАТУСОВ ──────────────────────────────────────

STATUS_MARK = {
    "scheduled": "●",   # ждёт (яркая точка)
    "completed": "✓",   # состоялся (галка)
    "no_show":   "—",   # не пришли (тире)
    "cancelled": "✕",   # отменён (крестик)
}

STATUS_WORD = {
    "scheduled": "ждёт",
    "completed": "состоялся",
    "no_show":   "не пришли",
    "cancelled": "отменён",
}
