"""
Handler-ы «моих записей» и отмены клиентом с причиной.

Включает:
  • список записей клиента с пагинацией (client_my_appointments / history_page_*)
  • карточку одной записи (my_appt_*)
  • подтверждение и выбор причины отмены (my_appt_cancel_* / cr_*)
  • reply-кнопку «мои записи»
  • no-op cal_noop (для неактивных кнопок календаря/пагинации)

Вынесено из client.py ради читаемости. Booking-flow остался в client.py.
"""
import logging
import math
from datetime import datetime

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from constants import MONTHS_RU, WEEKDAYS_SHORT_RU
from db import (
    count_user_appointments,
    get_user_appointments_page,
    get_appointment_by_id,
    cancel_appointment_by_client,
    get_master,
    log_admin_action,
)
from keyboards.inline import cancel_reason_keyboard, CANCEL_REASONS, get_history_pagination_kb
from utils.callbacks import parse_callback
from utils.notifications import admin_dismiss_kb, broadcast_to_admins, notify_master
from utils.ui import (
    DIVIDER_SOFT,
    ARROW_SOFT, ARROW_DO, ARROW_BACK, REPEAT, CLOSE,
    price as fmt_price,
    date_soft, date_tiny,
    STATUS_MARK, status_word,
    h,
)
from db.clients import get_user_lang
from utils.i18n import t

logger = logging.getLogger(__name__)
router = Router()

_HISTORY_PER_PAGE = 5


def _date_human(date_str: str) -> str:
    """Конвертирует YYYY-MM-DD → '15 января, пт'."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.day} {MONTHS_RU[dt.month - 1]}, {WEEKDAYS_SHORT_RU[dt.weekday()]}"
    except ValueError:
        return date_str


def _render_history_page(
    appointments: list[dict],
    page: int,
    total_pages: int,
    lang: str = "ru",
) -> tuple[str, InlineKeyboardMarkup]:
    """Формирует текст и клавиатуру для одной страницы истории записей."""
    lines: list[str] = [f"{t('history_title', lang)}\n{DIVIDER_SOFT}"]
    buttons: list[list[InlineKeyboardButton]] = []
    last_completed = None

    open_label = "ochish" if lang == "uz" else "открыть"
    repeat_label = "takrorlash" if lang == "uz" else "повторить"

    for appt in appointments:
        mark = STATUS_MARK.get(appt["status"], "·")
        word = status_word(appt["status"], lang)
        date_label = date_tiny(appt["date"], lang)
        svc_short = appt["service_name"][:45] + ("…" if len(appt["service_name"]) > 45 else "")

        lines.append(
            f"<i>{mark}</i>  <b>{date_label}</b>  ·  <code>{appt['time']}</code>\n"
            f"     {h(svc_short.lower())}  ·  <i>{word}</i>"
        )

        if appt["status"] == "completed" and last_completed is None:
            last_completed = appt

    first_scheduled = next((a for a in appointments if a["status"] == "scheduled"), None)
    if first_scheduled:
        svc_short_sched = first_scheduled["service_name"][:35] + ("…" if len(first_scheduled["service_name"]) > 35 else "")
        buttons.append([InlineKeyboardButton(
            text=f"{ARROW_SOFT} {open_label}: {svc_short_sched.lower()}",
            callback_data=f"my_appt_{first_scheduled['id']}",
        )])

    pagination_kb = get_history_pagination_kb(page, total_pages)
    if pagination_kb:
        buttons.extend(pagination_kb.inline_keyboard)

    if last_completed:
        svc_short = last_completed["service_name"][:45] + ("…" if len(last_completed["service_name"]) > 45 else "")
        buttons.append([InlineKeyboardButton(
            text=f"{REPEAT}  {repeat_label} · {svc_short.lower()}",
            callback_data=f"quick_rebook_{last_completed['id']}",
        )])

    text = "\n\n".join(lines)
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(F.data == "cal_noop")
async def cb_noop(callback: CallbackQuery):
    """No-op для неактивных кнопок (счётчик страниц и т.д.)."""
    await callback.answer()


@router.callback_query(F.data == "client_my_appointments")
async def cb_my_appointments(callback: CallbackQuery, state: FSMContext):
    """Показать записи клиента (первая страница)."""
    await state.clear()
    lang = await get_user_lang(callback.from_user.id)
    total = await count_user_appointments(callback.from_user.id)
    if total == 0:
        book_btn = t("btn_book", lang)
        try:
            await callback.message.edit_text(
                t("history_empty", lang),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text=f"{ARROW_DO} {book_btn}", callback_data="client_restart"),
                ]]),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
        await callback.answer()
        return

    total_pages = math.ceil(total / _HISTORY_PER_PAGE)
    appointments = await get_user_appointments_page(callback.from_user.id, page=0, per_page=_HISTORY_PER_PAGE)
    text, kb = _render_history_page(appointments, 0, total_pages, lang)

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("history_page_"))
async def on_history_page(callback: CallbackQuery):
    """Переключение страницы истории записей."""
    lang = await get_user_lang(callback.from_user.id)
    parts = parse_callback(callback.data, "history_page", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    page = int(parts[0])

    total = await count_user_appointments(callback.from_user.id)
    total_pages = math.ceil(total / _HISTORY_PER_PAGE)

    if page < 0 or page >= total_pages:
        await callback.answer()
        return

    appointments = await get_user_appointments_page(callback.from_user.id, page=page, per_page=_HISTORY_PER_PAGE)
    text, kb = _render_history_page(appointments, page, total_pages, lang)

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data.regexp(r"^my_appt_(\d+)$"))
async def cb_my_appt_detail(callback: CallbackQuery):
    """Детали записи клиента + кнопка отмены."""
    lang = await get_user_lang(callback.from_user.id)
    parts = parse_callback(callback.data, "my_appt", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    appt_id = int(parts[0])
    appt = await get_appointment_by_id(appt_id)

    if not appt or appt["user_id"] != callback.from_user.id:
        not_found = "Yozilish topilmadi." if lang == "uz" else "Запись не найдена."
        await callback.answer(not_found, show_alert=True)
        return

    mark = STATUS_MARK.get(appt["status"], "·")
    word = status_word(appt["status"], lang)
    master_line = ""
    if appt.get("master_id"):
        m = await get_master(appt["master_id"])
        if m:
            master_line = f"<i>{t('history_master', lang)} · {h(m['name'].title())}</i>\n"

    text = (
        f"<blockquote>"
        f"{t('history_visit', lang)}\n\n"
        f"{DIVIDER_SOFT}\n\n"
        f"<b>{h(appt['service_name'].lower())}</b>\n"
        f"{master_line}"
        f"\n"
        f"<i>{t('history_when', lang)}</i>       <code>{date_soft(appt['date'], lang)} · {appt['time']}</code>\n"
        f"<i>{t('history_price', lang)}</i>   <code>{fmt_price(appt['service_price'], lang)}</code>\n"
        f"\n"
        f"<i>{mark}  {word}</i>"
        f"</blockquote>"
    )

    kb_buttons = []

    if appt["status"] == "scheduled" and not appt.get("paid_at"):
        from utils.payment_ui import reconstruct_pay_url
        pay_url = reconstruct_pay_url(appt)
        if pay_url:
            from config import PAYMENT_LABEL
            kb_buttons.append([InlineKeyboardButton(
                text=f"💳 {PAYMENT_LABEL}",
                url=pay_url,
            )])

    if appt["status"] == "scheduled":
        kb_buttons.append([
            InlineKeyboardButton(text=t("history_cancel_btn", lang), callback_data=f"my_appt_cancel_{appt_id}"),
        ])
    kb_buttons.append([InlineKeyboardButton(
        text=t("history_back_btn", lang),
        callback_data="client_my_appointments",
    )])

    try:
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_buttons),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data.regexp(r"^my_appt_cancel_(\d+)$"))
async def cb_my_appt_cancel(callback: CallbackQuery):
    """Подтверждение отмены записи клиентом."""
    lang = await get_user_lang(callback.from_user.id)
    parts = parse_callback(callback.data, "my_appt_cancel", 1)
    if not parts:
        await callback.answer()
        return
    appt_id = int(parts[0])
    appt = await get_appointment_by_id(appt_id)

    if not appt or appt["user_id"] != callback.from_user.id:
        not_found = "Yozilish topilmadi." if lang == "uz" else "Запись не найдена."
        await callback.answer(not_found, show_alert=True)
        return

    try:
        await callback.message.edit_text(
            f"{t('history_cancel_confirm_q', lang)}\n\n"
            f"<blockquote><b>{h(appt['service_name'].lower())}</b>\n"
            f"<i>{date_soft(appt['date'], lang)} · {appt['time']}</i></blockquote>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text=t("history_cancel_yes", lang), callback_data=f"my_appt_cancel_yes_{appt_id}"),
                    InlineKeyboardButton(text=t("history_cancel_no", lang), callback_data=f"my_appt_{appt_id}"),
                ]
            ]),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data.regexp(r"^my_appt_cancel_yes_(\d+)$"))
async def cb_my_appt_cancel_yes(callback: CallbackQuery):
    """Показать выбор причины отмены."""
    lang = await get_user_lang(callback.from_user.id)
    parts = parse_callback(callback.data, "my_appt_cancel_yes", 1)
    if not parts:
        await callback.answer()
        return
    appt_id = int(parts[0])
    appt = await get_appointment_by_id(appt_id)

    if not appt or appt["user_id"] != callback.from_user.id:
        not_found = "Yozilish topilmadi." if lang == "uz" else "Запись не найдена."
        await callback.answer(not_found, show_alert=True)
        return

    reason_prompt = "<i>nima bo'ldi?</i>" if lang == "uz" else "<i>что случилось?</i>"
    try:
        await callback.message.edit_text(
            f"{reason_prompt}\n\n"
            f"<blockquote><b>{h(appt['service_name'].lower())}</b>\n"
            f"<i>{date_soft(appt['date'], lang)} · {appt['time']}</i></blockquote>",
            reply_markup=cancel_reason_keyboard(appt_id, lang),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data.regexp(r"^cr_(\w+)_(\d+)$"))
async def cb_cancel_with_reason(callback: CallbackQuery):
    """Реальная отмена с сохранением причины."""
    parts = parse_callback(callback.data, "cr", 2)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    reason_key = parts[0]
    # Whitelist: подделанный callback (cr_foo_123) не должен тащить пустую
    # reason в admin_logs и broadcast. Клавиатура генерит только ключи из
    # CANCEL_REASONS — всё остальное подлог.
    if reason_key not in CANCEL_REASONS:
        logger.warning("Unknown cancel reason_key=%s from user_id=%s", reason_key, callback.from_user.id)
        await callback.answer()
        return
    appt_id = int(parts[1])
    user_id = callback.from_user.id

    reason_label = CANCEL_REASONS[reason_key]
    success = await cancel_appointment_by_client(appt_id, user_id, reason=reason_label)
    if not success:
        await callback.answer("Не удалось отменить запись.", show_alert=True)
        return

    appt = await get_appointment_by_id(appt_id)

    # Уведомить админа с причиной. С кнопкой закрытия, иначе сообщение
    # висит в чате и отвлекает от админ-панели.
    reason_line = f"\n💬 Причина: {h(reason_label)}" if reason_label else ""
    await broadcast_to_admins(
        callback.bot,
        f"⚠️ <b>Клиент отменил запись</b>\n\n"
        f"👤 {h(appt['name'])} ({h(appt['phone'])})\n"
        f"📅 {_date_human(appt['date'])}  ·  {appt['time']}\n"
        f"💅 {h(appt['service_name'])}"
        f"{reason_line}",
        reply_markup=admin_dismiss_kb(),
        log_context="client cancellation",
    )

    # Уведомление мастера об отмене
    if appt and appt.get("master_id"):
        try:
            await notify_master(
                callback.bot, appt["master_id"], "cancelled",
                {"date": appt["date"], "time": appt["time"],
                 "client_name": appt["name"], "service_name": appt["service_name"]},
            )
        except Exception:
            logger.error("Ошибка уведомления мастера об отмене", exc_info=True)

    await log_admin_action(
        admin_id=0,
        action="client_cancelled",
        target_type="appointment",
        target_id=appt_id,
        details=f"Клиент {appt['name']} отменил запись. Причина: {reason_label}",
    )

    lang = await get_user_lang(callback.from_user.id)
    if lang == "uz":
        txt = "<i>yozilish bekor qilindi.</i>\n\n<i>fikringiz o'zgarsa — biz shu yerdamiz.</i>"
        btn = f"{ARROW_DO} qayta yozilish"
    else:
        txt = "<i>запись ушла.</i>\n\n<i>если передумаешь — мы рядом.</i>"
        btn = f"{ARROW_DO} записаться снова"
    try:
        await callback.message.edit_text(
            txt,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=btn, callback_data="client_restart"),
            ]]),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await callback.answer(t("history_cancelled", lang))


@router.message(F.text.in_({"мои записи", "mening yozilishlarim", "Mening yozuvlarim"}))
async def btn_my_appointments(message: Message, state: FSMContext):
    """Кнопка reply-клавиатуры — сбрасывает FSM и показывает записи клиента (стр. 1)."""
    await state.clear()
    lang = await get_user_lang(message.from_user.id)
    total = await count_user_appointments(message.from_user.id)
    if total == 0:
        book_btn = t("btn_book", lang)
        await message.answer(
            t("history_empty", lang),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=f"{ARROW_DO} {book_btn}", callback_data="client_restart"),
            ]]),
            parse_mode="HTML",
        )
        return

    total_pages = math.ceil(total / _HISTORY_PER_PAGE)
    appointments = await get_user_appointments_page(message.from_user.id, page=0, per_page=_HISTORY_PER_PAGE)
    text, kb = _render_history_page(appointments, 0, total_pages, lang)

    await message.answer(text, reply_markup=kb, parse_mode="HTML")
