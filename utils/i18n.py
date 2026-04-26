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
        "ru": "выбери язык · tilni tanlang",
        "uz": "выбери язык · tilni tanlang",
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
        "ru": "✅ язык изменён на русский.",
        "uz": "✅ til o'zgartirildi — o'zbekcha.",
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
    "btn_what_today": {"ru": "что сегодня?", "uz": "bugun nima?"},

    # ─── 3. Booking flow ───────────────────────────────────────────────────
    "book_no_services": {
        "ru": "Пока нет доступных услуг. Скоро вернёмся.",
        "uz": "Hozircha xizmatlar yo'q. Tez orada qaytamiz.",
    },
    "book_category_prompt": {
        "ru": "<b>Выбери направление</b>",
        "uz": "<b>Yo'nalishni tanlang</b>",
    },
    "book_services_prompt": {
        "ru": "<b>Выбери услугу</b>",
        "uz": "<b>Xizmatni tanlang</b>",
    },
    "book_master_prompt": {
        "ru": "<b>Выбери мастера</b>",
        "uz": "<b>Ustani tanlang</b>",
    },
    "book_any_master": {
        "ru": "Любой свободный",
        "uz": "Bo'sh usta",
    },
    "book_date_prompt": {
        "ru": "<b>Выбери дату</b>",
        "uz": "<b>Sanani tanlang</b>",
    },
    "book_time_prompt": {
        "ru": "<b>Выбери время</b>",
        "uz": "<b>Vaqtni tanlang</b>",
    },
    "book_no_free_slots": {
        "ru": "На этот день свободных окон нет.\nПопробуй другую дату.",
        "uz": "Bu kunda bo'sh vaqt yo'q.\nBoshqa sanani tanlang.",
    },
    "book_addons_prompt": {
        "ru": "<b>Добавить к услуге?</b>",
        "uz": "<b>Xizmatga qo'shamizmi?</b>",
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
        "ru": "<b>Как вас зовут?</b>",
        "uz": "<b>Ismingizni ayting</b>",
    },
    "book_name_too_short": {
        "ru": "Имя коротковато. 2–64 символа, только буквы и пробелы.",
        "uz": "Ism juda qisqa. 2–64 belgi, faqat harflar va probel.",
    },
    "book_ask_phone": {
        "ru": "📱 <b>Поделитесь номером</b>\nКнопкой ниже или текстом.",
        "uz": "📱 <b>Telefon raqamingizni ulashing</b>\nPastdagi tugma yoki matn orqali.",
    },
    "book_phone_share_btn": {
        "ru": "📱 Поделиться номером",
        "uz": "📱 Raqamni ulashish",
    },
    "book_phone_invalid": {
        "ru": "Непохоже на телефон. Пришлите ещё раз.",
        "uz": "Telefon raqamiga o'xshamaydi. Qayta yuboring.",
    },
    "book_confirm_header": {
        "ru": "<b>Проверьте данные</b>",
        "uz": "<b>Ma'lumotlarni tekshiring</b>",
    },
    "book_confirm_when": {"ru": "Когда:       ", "uz": "Sana:        "},
    "book_confirm_price": {"ru": "К оплате:    ", "uz": "To'lov:      "},
    "book_confirm_duration": {"ru": "Длительность:", "uz": "Davomiyligi: "},
    "book_confirm_master": {"ru": "Мастер:      ", "uz": "Usta:        "},
    "book_service_unavailable": {
        "ru": "услуга недоступна. начни заново: /start",
        "uz": "xizmat mavjud emas. qayta boshlang: /start",
    },
    "book_master_unavailable": {
        "ru": "⚠️ мастер больше недоступен.\nначни заново: /start",
        "uz": "⚠️ usta endi mavjud emas.\nqayta boshlang: /start",
    },
    "book_slot_taken": {
        "ru": "⚠️ кто-то оказался быстрее. выбери другое время.",
        "uz": "⚠️ kimdir siz bilan ayni vaqtga yozildi. boshqa vaqtni tanlang.",
    },
    "book_generic_error": {
        "ru": "⚠️ что-то пошло не так.\nпопробуй /start.",
        "uz": "⚠️ nimadir noto'g'ri ketdi.\n/start buyrug'ini yuboring.",
    },
    "book_profile_saved_question": {
        "ru": "<b>использовать сохранённое имя и телефон?</b>",
        "uz": "<b>saqlangan ism va telefonni ishlatamizmi?</b>",
    },
    "book_profile_use_saved": {
        "ru": "✅ да",
        "uz": "✅ ha",
    },
    "book_profile_new": {
        "ru": "✏ ввести заново",
        "uz": "✏ qaytadan kiritish",
    },
    "book_repeat_header": {
        "ru": "🔄 <b>ПОВТОРЯЕМ</b>",
        "uz": "🔄 <b>TAKRORLAYMIZ</b>",
    },
    "book_repeat_appt_not_found": {
        "ru": "Запись не найдена.",
        "uz": "Yozuv topilmadi.",
    },
    "book_repeat_service_inactive": {
        "ru": "Эта услуга больше не доступна.",
        "uz": "Bu xizmat endi mavjud emas.",
    },

    # ─── 4. История записей / мои записи ───────────────────────────────────
    "history_empty": {
        "ru": "📋 <b>У вас пока нет записей</b>\n\nПервая запись — пара касаний.",
        "uz": "📋 <b>Hozircha yozuvlar yo'q</b>\n\nBirinchi yozilish — bir necha bosish.",
    },
    "history_title": {
        "ru": "📋 <b>МОИ ЗАПИСИ</b>",
        "uz": "📋 <b>MENING YOZUVLARIM</b>",
    },
    "history_visit": {
        "ru": "💅 <b>ВАШ ВИЗИТ</b>",
        "uz": "💅 <b>SIZNING TASHRIFINGIZ</b>",
    },
    "history_when": {"ru": "Когда:    ", "uz": "Sana:     "},
    "history_price": {"ru": "К оплате: ", "uz": "To'lov:   "},
    "history_master": {"ru": "Мастер:   ", "uz": "Usta:     "},
    "history_cancel_btn": {
        "ru": "❌ Отменить запись",
        "uz": "❌ Yozilishni bekor qilish",
    },
    "history_back_btn": {
        "ru": "← Мои записи",
        "uz": "← Mening yozuvlarim",
    },
    "history_cancelled": {
        "ru": "Запись отменена",
        "uz": "Yozilish bekor qilindi",
    },
    "history_cancel_confirm_q": {
        "ru": "<b>Точно отменить запись?</b>",
        "uz": "<b>Yozilishni aniq bekor qilasizmi?</b>",
    },
    "history_cancel_paid_warning": {
        "ru": "⚠️ Запись оплачена. Деньги вернёт салон — свяжись для возврата.",
        "uz": "⚠️ Yozilish to'langan. Salon pulni qaytaradi — bog'laning.",
    },
    "history_cancel_yes": {
        "ru": "❌ Да, отменить",
        "uz": "❌ Ha, bekor qilish",
    },
    "history_cancel_no": {
        "ru": "← Нет",
        "uz": "← Yo'q",
    },
    "history_page_of": {"ru": "стр. {page}/{total}", "uz": "sahifa {page}/{total}"},
    # B-стиль «Мои записи»: три секции — ближайшая карточка / ещё предстоящие / история.
    "history_nearest_title": {
        "ru": "БЛИЖАЙШАЯ",
        "uz": "YAQIN YOZILISH",
    },
    "history_upcoming_title": {
        "ru": "ЕЩЁ ПРЕДСТОЯЩИЕ",
        "uz": "YANA KUTILAYOTGAN",
    },
    "history_past_title": {
        "ru": "ИСТОРИЯ",
        "uz": "TARIX",
    },
    "history_nearest_service": {"ru": "Услуга:    ", "uz": "Xizmat:    "},
    "history_nearest_master": {"ru": "Мастер:    ", "uz": "Usta:      "},
    "history_nearest_when": {"ru": "Когда:     ", "uz": "Vaqt:      "},
    "history_nearest_price": {"ru": "К оплате:  ", "uz": "To'lov:    "},
    "pay_status_wait": {"ru": "⏳ ждёт оплаты", "uz": "⏳ to'lov kutilmoqda"},
    "pay_status_paid": {"ru": "💰 оплачено", "uz": "💰 to'langan"},
    "rel_today": {"ru": "сегодня", "uz": "bugun"},
    "rel_tomorrow": {"ru": "завтра", "uz": "ertaga"},
    "btn_open_nearest": {"ru": "📋 Открыть", "uz": "📋 Ochish"},
    "btn_repeat_last": {"ru": "🔄 Повторить", "uz": "🔄 Takrorlash"},

    # ─── 5. Отзывы ─────────────────────────────────────────────────────────
    "review_prompt": {
        "ru": "<b>как прошло?</b>",
        "uz": "<b>qanday o'tdi?</b>",
    },
    "review_thanks": {
        "ru": "✨ спасибо",
        "uz": "✨ rahmat",
    },
    "review_comment_prompt": {
        "ru": "хочешь что-то добавить? напиши одним сообщением или пропусти.",
        "uz": "biror narsa qo'shmoqchimisiz? bir xabar bilan yozing yoki o'tkazib yuboring.",
    },
    "review_skip_btn": {
        "ru": "пропустить",
        "uz": "o'tkazib yuborish",
    },
    "review_saved": {
        "ru": "✅ записано. до встречи в следующий раз.",
        "uz": "✅ qabul qilindi. keyingi safargacha.",
    },

    # ─── 6. Напоминания ─────────────────────────────────────────────────────
    "reminder_24h_title": {
        "ru": "<b>завтра у тебя запись</b>",
        "uz": "<b>ertaga sizning tashrifingiz</b>",
    },
    "reminder_2h_title": {
        "ru": "<b>через пару часов жду</b>",
        "uz": "<b>bir necha soatdan keyin kutamiz</b>",
    },

    # ─── 7. Платежи / возврат ──────────────────────────────────────────────
    "pay_link_text": {
        "ru": "💳 ссылка на оплату:",
        "uz": "💳 to'lov havolasi:",
    },
    "pay_btn": {
        "ru": "Оплатить",
        "uz": "To'lov qilish",
    },
    "review_after_visit_title": {
        "ru": "💅 <b>Спасибо за визит!</b>\n\nну как {service}?",
        "uz": "💅 <b>Tashrifingiz uchun rahmat!</b>\n\n{service} yoqdimi?",
    },
    "pay_received_client": {
        "ru": "✅ <b>оплата получена.</b>\nжду тебя.",
        "uz": "✅ <b>to'lov qabul qilindi.</b>\nsizni kutamiz.",
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
