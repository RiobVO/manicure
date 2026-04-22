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
    "btn_book": {"ru": "записаться", "uz": "yozilish"},
    "btn_my_appts": {"ru": "мои записи", "uz": "mening yozilishlarim"},
    "btn_back": {"ru": "↩ назад", "uz": "↩ orqaga"},
    "btn_cancel": {"ru": "❌ отменить", "uz": "❌ bekor qilish"},
    "btn_confirm_yes": {"ru": "✅ да, записаться", "uz": "✅ ha, yozilaman"},
    "btn_confirm_no": {"ru": "❌ передумал", "uz": "❌ fikrim o'zgardi"},
    "btn_pick_another": {"ru": "› выбрать другое", "uz": "› boshqasini tanlash"},
    "btn_repeat": {"ru": "↻ повторить", "uz": "↻ takrorlash"},
    "btn_what_today": {"ru": "<i>что сегодня?</i>", "uz": "<i>bugun nima?</i>"},

    # ─── 3. Booking flow ───────────────────────────────────────────────────
    "book_no_services": {
        "ru": "<i>пока нет доступных услуг.</i>\n\n<i>скоро вернёмся.</i>",
        "uz": "<i>hozircha xizmatlar yo'q.</i>\n\n<i>tez orada qaytamiz.</i>",
    },
    "book_category_prompt": {
        "ru": "<i>ручки или ножки?</i>",
        "uz": "<i>Qo'llarmi yoki oyoqlar?</i>",
    },
    "book_services_prompt": {
        "ru": "<i>что красим?</i>",
        "uz": "<i>Qanday xizmatni tanlaymiz?</i>",
    },
    "book_master_prompt": {
        "ru": "<i>кто тебя принимает?</i>",
        "uz": "<i>qaysi usta qabul qiladi?</i>",
    },
    "book_any_master": {
        "ru": "любой свободный",
        "uz": "bo'sh bo'lgan usta",
    },
    "book_date_prompt": {
        "ru": "<i>выбери дату.</i>",
        "uz": "<i>sanani tanlang.</i>",
    },
    "book_time_prompt": {
        "ru": "<i>выбери время.</i>",
        "uz": "<i>vaqtni tanlang.</i>",
    },
    "book_no_free_slots": {
        "ru": "<i>на этот день свободных окон нет.</i>\n<i>попробуй другую дату.</i>",
        "uz": "<i>bu kunda bo'sh vaqt yo'q.</i>\n<i>boshqa sanani tanlang.</i>",
    },
    "book_addons_prompt": {
        "ru": "<i>добавить что-то к услуге?</i>",
        "uz": "<i>xizmatga nimadir qo'shamizmi?</i>",
    },
    "book_addons_skip": {
        "ru": "без дополнений",
        "uz": "qo'shimchasiz",
    },
    "book_addons_done": {
        "ru": "готово",
        "uz": "tayyor",
    },
    "book_ask_name": {
        "ru": "<i>как тебя зовут?</i>",
        "uz": "<i>ismingiz nima?</i>",
    },
    "book_name_too_short": {
        "ru": "<i>имя коротковато. 2-64 символа, только буквы и пробелы.</i>",
        "uz": "<i>ism juda qisqa. 2-64 belgi, faqat harflar va probel.</i>",
    },
    "book_ask_phone": {
        "ru": "<i>пришли номер — кнопкой ниже или текстом.</i>",
        "uz": "<i>telefon raqamini yuboring — pastdagi tugma yoki matn orqali.</i>",
    },
    "book_phone_share_btn": {
        "ru": "📱 поделиться номером",
        "uz": "📱 raqamni ulashish",
    },
    "book_phone_invalid": {
        "ru": "<i>непохоже на телефон. пришли ещё раз.</i>",
        "uz": "<i>telefon raqamiga o'xshamaydi. qayta yuboring.</i>",
    },
    "book_confirm_header": {
        "ru": "<b><i>всё верно?</i></b>",
        "uz": "<b><i>Ma'lumotlar to'g'rimi?</i></b>",
    },
    "book_confirm_when": {"ru": "когда", "uz": "Sana va vaqt"},
    "book_confirm_price": {"ru": "стоимость", "uz": "Xizmat narxi"},
    "book_confirm_duration": {"ru": "длительность", "uz": "Davomiyligi"},
    "book_confirm_master": {"ru": "мастер", "uz": "Usta"},
    "book_service_unavailable": {
        "ru": "услуга недоступна. начни заново: /start",
        "uz": "xizmat mavjud emas. qayta boshlang: /start",
    },
    "book_master_unavailable": {
        "ru": "<i>мастер больше недоступен.</i>\n<i>начни заново: /start</i>",
        "uz": "<i>usta endi mavjud emas.</i>\n<i>qayta boshlang: /start</i>",
    },
    "book_slot_taken": {
        "ru": "<i>кто-то оказался быстрее. выбери другое время.</i>",
        "uz": "<i>kimdir siz bilan ayni vaqtga yozildi. boshqa vaqtni tanlang.</i>",
    },
    "book_generic_error": {
        "ru": "<i>что-то пошло не так.</i>\n<i>попробуй /start.</i>",
        "uz": "<i>nimadir noto'g'ri ketdi.</i>\n<i>/start buyrug'ini yuboring.</i>",
    },
    "book_profile_saved_question": {
        "ru": "<i>использовать сохранённое имя и телефон?</i>",
        "uz": "<i>saqlangan ism va telefonni ishlatamizmi?</i>",
    },
    "book_profile_use_saved": {
        "ru": "✅ да",
        "uz": "✅ ha",
    },
    "book_profile_new": {
        "ru": "✏ ввести заново",
        "uz": "✏ qaytadan kiritish",
    },

    # ─── 4. История записей / мои записи ───────────────────────────────────
    "history_empty": {
        "ru": "<i>пока ничего.</i>\n\n<i>первая запись — пара касаний.</i>",
        "uz": "<i>hozircha hech narsa yo'q.</i>\n\n<i>birinchi yozilish — bir necha bosish.</i>",
    },
    "history_title": {
        "ru": "<b><i>твои записи</i></b>",
        "uz": "<b><i>sizning yozilishlaringiz</i></b>",
    },
    "history_visit": {
        "ru": "<b><i>твой визит</i></b>",
        "uz": "<b><i>sizning tashrifingiz</i></b>",
    },
    "history_when": {"ru": "когда", "uz": "qachon"},
    "history_price": {"ru": "стоимость", "uz": "narxi"},
    "history_master": {"ru": "мастер", "uz": "usta"},
    "history_cancel_btn": {
        "ru": "✕ отменить запись",
        "uz": "✕ yozilishni bekor qilish",
    },
    "history_back_btn": {
        "ru": "← мои записи",
        "uz": "← mening yozilishlarim",
    },
    "history_cancelled": {
        "ru": "Запись отменена",
        "uz": "Yozilish bekor qilindi",
    },
    "history_cancel_confirm_q": {
        "ru": "<i>точно отменить запись?</i>",
        "uz": "<i>yozilishni aniq bekor qilasizmi?</i>",
    },
    "history_cancel_yes": {
        "ru": "✕ да, отменить",
        "uz": "✕ ha, bekor qilish",
    },
    "history_cancel_no": {
        "ru": "← нет",
        "uz": "← yo'q",
    },
    "history_page_of": {"ru": "стр. {page}/{total}", "uz": "sahifa {page}/{total}"},

    # ─── 5. Отзывы ─────────────────────────────────────────────────────────
    "review_prompt": {
        "ru": "<i>как прошло?</i>",
        "uz": "<i>qanday o'tdi?</i>",
    },
    "review_thanks": {
        "ru": "<i>спасибо ✧</i>",
        "uz": "<i>rahmat ✧</i>",
    },
    "review_comment_prompt": {
        "ru": "<i>хочешь что-то добавить? напиши одним сообщением или пропусти.</i>",
        "uz": "<i>biror narsa qo'shmoqchimisiz? bir xabar bilan yozing yoki o'tkazib yuboring.</i>",
    },
    "review_skip_btn": {
        "ru": "пропустить",
        "uz": "o'tkazib yuborish",
    },
    "review_saved": {
        "ru": "<i>записано. до встречи в следующий раз.</i>",
        "uz": "<i>qabul qilindi. keyingi safargacha.</i>",
    },

    # ─── 6. Напоминания ─────────────────────────────────────────────────────
    "reminder_24h_title": {
        "ru": "<b><i>завтра у тебя запись</i></b>",
        "uz": "<b><i>ertaga sizning tashrifingiz</i></b>",
    },
    "reminder_2h_title": {
        "ru": "<b><i>через пару часов жду</i></b>",
        "uz": "<b><i>bir necha soatdan keyin kutamiz</i></b>",
    },

    # ─── 7. Платежи / возврат ──────────────────────────────────────────────
    "pay_link_text": {
        "ru": "<i>ссылка на оплату:</i>",
        "uz": "<i>to'lov havolasi:</i>",
    },
    "pay_btn": {
        "ru": "Оплатить",
        "uz": "To'lov",
    },
    "pay_received_client": {
        "ru": "<i>✓ оплата получена.</i>\n<i>жду тебя.</i>",
        "uz": "<i>✓ to'lov qabul qilindi.</i>\n<i>kutamiz.</i>",
    },
    "refund_needed_intro": {
        "ru": "💰 Оплата подлежит возврату.",
        "uz": "💰 To'lov qaytariladi.",
    },
    "refund_contact_known": {
        "ru": "📞 по вопросу возврата оплаты — {contact}",
        "uz": "📞 to'lovni qaytarish uchun — {contact}",
    },
    "refund_contact_unknown": {
        "ru": "📞 свяжись с салоном по вопросу возврата оплаты",
        "uz": "📞 to'lovni qaytarish uchun salon bilan bog'laning",
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
