"""
Интернационализация клиентского интерфейса (Phase 3 v.4).

Поддерживаемые языки:
    ru — русский (дефолт для существующих клиентов)
    uz — O'zbek (латиница, как официальный алфавит Узбекистана)

Admin-панель остаётся на русском — Phase 3 касается только клиентских
сообщений и кнопок.

Usage:
    from utils.i18n import t, Lang

    text = t("greeting_hours", Lang.RU, hours=3)
    text = t("greeting_hours", Lang.UZ, hours=3)

Правила:
    • Ключ — snake_case_english, описывает смысл ('booking_confirm_question').
    • Значение — строка с плейсхолдерами в стиле str.format ({name}, {hours}).
    • Если для ключа нет перевода на язык — fallback на ru + warning в логах.
    • Таблицы НЕ генерируются автоматически, каждый ключ вручную добавляется
      сюда разработчиком. Это намеренно: каждое изменение текста — коммит.
"""
from __future__ import annotations

import logging
from typing import Final

logger = logging.getLogger(__name__)


class Lang:
    RU: Final[str] = "ru"
    UZ: Final[str] = "uz"
    DEFAULT: Final[str] = "ru"

    @staticmethod
    def normalize(raw: str | None) -> str:
        """Защита от кривых значений в БД — 'ru' | 'uz'. Прочее → дефолт."""
        if raw == Lang.UZ:
            return Lang.UZ
        return Lang.RU


# ─────────────────────────────────────────────────────────────────────────────
# Таблица переводов.
#
# Структура: { key: { "ru": "...", "uz": "..." } }
#
# Блоки маркированы комментариями — держим их в том же порядке что в спеке:
#   1. Переключатель языка (lang_*).
#   2. Общие кнопки (btn_*).
#   3. Приветствия / hero (greeting_*, booking_done_*).
#   4. Booking flow (book_*).
#   5. Мои записи (history_*).
#   6. Отзывы (review_*).
#   7. Напоминания (reminder_*).
#   8. Платежи (pay_*, refund_*).
#   9. Ошибки / fallback (err_*).
# ─────────────────────────────────────────────────────────────────────────────
TRANSLATIONS: dict[str, dict[str, str]] = {
    # ─── 1. Переключатель языка ────────────────────────────────────────────
    "lang_picker_prompt": {
        "ru": "<i>выбери язык · tilni tanlang</i>",
        "uz": "<i>выбери язык · tilni tanlang</i>",
    },
    "lang_btn_ru": {
        "ru": "🇷🇺 Русский",
        "uz": "🇷🇺 Русский",
    },
    "lang_btn_uz": {
        "ru": "🇺🇿 O'zbek",
        "uz": "🇺🇿 O'zbek",
    },
    "lang_changed": {
        "ru": "<i>язык изменён на русский.</i>",
        "uz": "<i>til o'zgartirildi — o'zbekcha.</i>",
    },
    "lang_change_button": {
        "ru": "🌐 Язык / Til",
        "uz": "🌐 Язык / Til",
    },

    # ─── 2. Общие кнопки клиента ───────────────────────────────────────────
    "btn_book": {
        "ru": "записаться",
        "uz": "yozilish",
    },
    "btn_my_appts": {
        "ru": "мои записи",
        "uz": "mening yozilishlarim",
    },
    "btn_back": {
        "ru": "↩ назад",
        "uz": "↩ orqaga",
    },
    "btn_cancel": {
        "ru": "❌ отменить",
        "uz": "❌ bekor qilish",
    },
    "btn_confirm_yes": {
        "ru": "✅ да, записаться",
        "uz": "✅ ha, yozilaman",
    },
    "btn_confirm_no": {
        "ru": "❌ передумал",
        "uz": "❌ fikrim o'zgardi",
    },
}


def t(key: str, lang: str = Lang.DEFAULT, **kwargs) -> str:
    """
    Перевести ключ на нужный язык. Отсутствующий ключ/перевод → ru-fallback
    + warning в логах (не роняем пользовательский UX).
    """
    lang = Lang.normalize(lang)
    entry = TRANSLATIONS.get(key)
    if entry is None:
        logger.warning("i18n: отсутствует ключ %r", key)
        return key  # Видно в UI, чтобы сразу заметить.
    text = entry.get(lang) or entry.get(Lang.DEFAULT)
    if text is None:
        logger.warning("i18n: нет ни одного перевода для ключа %r", key)
        return key
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError, ValueError) as exc:
            logger.warning("i18n: не смогли отформатировать %r (%s)", key, exc)
    return text
