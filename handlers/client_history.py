"""
Handler-ы «моих записей» и отмены клиентом с причиной.

Включает:
  • список записей клиента в B-стиле: ближайшая карточкой + ещё предстоящие +
    история. Без пагинации — ограничение 30 записей в запросе, история
    усекается до 5 последних (при 10+ историчных записях это не раздражает).
    Когда клиенты начнут набирать по 50+ записей — добавим пагинацию историей
    отдельно.
  • карточку одной записи (my_appt_*)
  • подтверждение и выбор причины отмены (my_appt_cancel_* / cr_*)
  • reply-кнопку «мои записи»
  • no-op cal_noop (для неактивных кнопок календаря/пагинации)

Вынесено из client.py ради читаемости. Booking-flow остался в client.py.
"""
import logging
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
    get_user_appointments_full,
    get_appointment_by_id,
    cancel_appointment_by_client,
    get_master,
    log_admin_action,
)
from keyboards.inline import cancel_reason_keyboard, CANCEL_REASONS
from utils.callbacks import parse_callback
from utils.notifications import admin_dismiss_kb, broadcast_to_admins, notify_master
from utils.timezone import now_local
from utils.ui import (
    ARROW_DO,
    price as fmt_price,
    date_soft, date_tiny,
    status_word,
    h,
)
from db.clients import get_user_lang
from utils.i18n import t

logger = logging.getLogger(__name__)
router = Router()

_HISTORY_PAST_LIMIT = 5  # сколько прошлых записей показываем в блоке «История»
_FETCH_LIMIT = 30        # сколько всего записей тянем из БД за один рендер


def _date_human(date_str: str) -> str:
    """Конвертирует YYYY-MM-DD → '15 января, пт'. Для сообщений админам."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.day} {MONTHS_RU[dt.month - 1]}, {WEEKDAYS_SHORT_RU[dt.weekday()]}"
    except ValueError:
        return date_str


_STATUS_EMOJI = {
    "scheduled": "🕐",
    "completed": "✅",
    "no_show":   "➖",
    "cancelled": "❌",
}


def _relative_date(date_str: str, lang: str) -> str:
    """
    Относительная дата для клиентского UI:
      • сегодня → «сегодня» / «bugun»
      • завтра → «завтра» / «ertaga»
      • 2-6 дней → «пн · 27 апр» (short weekday + date) / «Du · 27 apr»
      • дальше → «27 апр» / «27 apr»
    Fallback на сырую строку при кривых данных.
    """
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return date_str
    today = now_local().date()
    delta = (dt - today).days
    if delta == 0:
        return t("rel_today", lang)
    if delta == 1:
        return t("rel_tomorrow", lang)
    # date_tiny даёт '27 апр · пн'; для 2-6 дней такого формата достаточно.
    # Для >6 дней отбросим weekday — слишком далеко, чтобы ориентироваться
    # по дню недели.
    tiny = date_tiny(date_str, lang)
    if 2 <= delta <= 6:
        return tiny
    # Берём только «число месяц», weekday усекаем.
    return tiny.split(" · ")[0]


def _payment_status_line(appt: dict, lang: str) -> str:
    """
    Короткий статус оплаты для предстоящей записи:
      • paid_at есть → 💰 оплачено
      • invoice есть, paid_at нет → ⏳ ждёт оплаты
      • нет ничего → пустая строка (платежи не подключены у этого салона)
    """
    if appt.get("paid_at"):
        return t("pay_status_paid", lang)
    if appt.get("payment_invoice_id"):
        return t("pay_status_wait", lang)
    return ""


def _split_upcoming_past(appts: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Разделить поток (DESC by date) на upcoming (scheduled + date>=today,
    ASC для «ближайшая первой») и past (остальное в DESC — свежие сверху).
    """
    today = now_local().strftime("%Y-%m-%d")
    upcoming: list[dict] = []
    past: list[dict] = []
    for a in appts:
        if a["status"] == "scheduled" and a["date"] >= today:
            upcoming.append(a)
        else:
            past.append(a)
    # DESC → ASC для upcoming: ближайшая должна быть первой.
    upcoming.reverse()
    return upcoming, past


async def _render_history_b_style(
    appts: list[dict], lang: str,
) -> tuple[str, InlineKeyboardMarkup]:
    """
    B-стиль «Мои записи»: ближайшая карточкой + ещё предстоящие + история.
    Возвращает (text, keyboard). Keyboard строится динамически в зависимости
    от наличия ближайшей записи и последней завершённой.

    Принимает готовый список записей, не делает SELECT — caller решает
    что делать с пустым списком (шапка vs список).
    """
    upcoming, past = _split_upcoming_past(appts)

    nearest = upcoming[0] if upcoming else None
    rest_upcoming = upcoming[1:]
    past_shown = past[:_HISTORY_PAST_LIMIT]

    lines: list[str] = [t("history_title", lang), ""]

    # ── Блок: БЛИЖАЙШАЯ ───────────────────────────────────────────────────
    if nearest:
        rel = _relative_date(nearest["date"], lang)
        pay_status = _payment_status_line(nearest, lang)

        # Мастер из JOIN — если NULL, показываем прочерк.
        master_name = "—"
        if nearest.get("master_name"):
            master_name = h(str(nearest["master_name"]).title())

        svc_label = t("history_nearest_service", lang)
        master_label = t("history_nearest_master", lang)
        when_label = t("history_nearest_when", lang)
        price_label = t("history_nearest_price", lang)

        price_cell = fmt_price(nearest["service_price"], lang)
        if pay_status:
            price_cell = f"{price_cell}  {pay_status}"

        lines.append(f"<b>{t('history_nearest_title', lang)}</b> · {rel}")
        lines.append(
            f"<code>"
            f"{svc_label}{h(nearest['service_name'])}\n"
            f"{master_label}{master_name}\n"
            f"{when_label}{rel} · {nearest['time']}\n"
            f"{price_label}{price_cell}"
            f"</code>"
        )

    # ── Блок: ЕЩЁ ПРЕДСТОЯЩИЕ ─────────────────────────────────────────────
    if rest_upcoming:
        lines.append("")
        lines.append(f"<b>{t('history_upcoming_title', lang)}</b>")
        lines.append("")
        for appt in rest_upcoming:
            rel = _relative_date(appt["date"], lang)
            pay_status = _payment_status_line(appt, lang)
            svc_short = appt["service_name"][:42] + ("…" if len(appt["service_name"]) > 42 else "")
            price_cell = fmt_price(appt["service_price"], lang)
            tail = f" · {pay_status}" if pay_status else ""
            lines.append(
                f"🕐 <b>{rel} · {appt['time']}</b> · {h(svc_short)}\n"
                f"   {price_cell}{tail}"
            )

    # ── Блок: ИСТОРИЯ ─────────────────────────────────────────────────────
    if past_shown:
        lines.append("")
        lines.append(f"<b>{t('history_past_title', lang)}</b>")
        lines.append("")
        for appt in past_shown:
            emoji = _STATUS_EMOJI.get(appt["status"], "•")
            short_date = date_tiny(appt["date"], lang).split(" · ")[0]  # «20 апр»
            svc_short = appt["service_name"][:36] + ("…" if len(appt["service_name"]) > 36 else "")
            price_cell = fmt_price(appt["service_price"], lang)
            lines.append(
                f"{emoji} <b>{short_date}</b> · {h(svc_short)} · {price_cell}"
            )
        if len(past) > _HISTORY_PAST_LIMIT:
            more = len(past) - _HISTORY_PAST_LIMIT
            more_ru = f"… и ещё {more}"
            more_uz = f"… yana {more} ta"
            lines.append("")
            lines.append(more_uz if lang == "uz" else more_ru)

    # Совсем пусто — но сюда по идее не приходим: caller отсекает до вызова.
    if not nearest and not rest_upcoming and not past_shown:
        return t("history_empty", lang), InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text=f"{ARROW_DO} {t('btn_book', lang)}",
                callback_data="client_restart",
            ),
        ]])

    # ── Клавиатура ────────────────────────────────────────────────────────
    # Сознательно не показываем здесь кнопку «💳 Оплатить». Когда у клиента
    # несколько предстоящих, одна общая кнопка «Оплатить» без привязки к
    # записи — путаница: непонятно что оплачиваешь. Pay-кнопка живёт в
    # детали конкретной записи (cb_my_appt_detail), там контекст явный.
    # На главной — одна кнопка «📋 открыть» с услугой+временем ближайшей,
    # клиент видит куда идёт.
    kb_rows: list[list[InlineKeyboardButton]] = []

    if nearest:
        rel = _relative_date(nearest["date"], lang)
        svc_short = nearest["service_name"][:28] + (
            "…" if len(nearest["service_name"]) > 28 else ""
        )
        open_label = f"📋 {svc_short} · {rel} · {nearest['time']}"
        kb_rows.append([InlineKeyboardButton(
            text=open_label,
            callback_data=f"my_appt_{nearest['id']}",
        )])

    # Кнопка «Повторить» — для самой свежей completed-записи (не cancelled).
    last_completed = next((a for a in past if a["status"] == "completed"), None)
    if last_completed:
        svc_short = last_completed["service_name"][:25] + (
            "…" if len(last_completed["service_name"]) > 25 else ""
        )
        kb_rows.append([InlineKeyboardButton(
            text=f"{t('btn_repeat_last', lang)}: {svc_short}",
            callback_data=f"quick_rebook_{last_completed['id']}",
        )])

    text = "\n".join(lines)
    return text, InlineKeyboardMarkup(inline_keyboard=kb_rows)


@router.callback_query(F.data == "cal_noop")
async def cb_noop(callback: CallbackQuery):
    """No-op для неактивных кнопок (счётчик страниц и т.д.)."""
    await callback.answer()


@router.callback_query(F.data == "client_my_appointments")
async def cb_my_appointments(callback: CallbackQuery, state: FSMContext):
    """Показать записи клиента (B-стиль: ближайшая + ещё + история)."""
    await callback.answer()  # ранний ack
    await state.clear()
    lang = await get_user_lang(callback.from_user.id)

    # Один SELECT вместо count+fetch: второй знает len(appts) сам.
    appts = await get_user_appointments_full(callback.from_user.id, limit=_FETCH_LIMIT)
    if not appts:
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
        return

    text, kb = await _render_history_b_style(appts, lang)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("history_page_"))
async def on_history_page(callback: CallbackQuery):
    """
    Старые пагинационные кнопки (history_page_N) ведут на тот же B-экран
    — пагинация больше не используется. Оставлено на случай если старые
    сообщения у клиента ещё висят в чате и он по ним тапнет.
    """
    await callback.answer()  # ранний ack
    lang = await get_user_lang(callback.from_user.id)
    appts = await get_user_appointments_full(callback.from_user.id, limit=_FETCH_LIMIT)
    text, kb = await _render_history_b_style(appts, lang)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass


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

    emoji = _STATUS_EMOJI.get(appt["status"], "•")
    word = status_word(appt["status"], lang)
    master_name = "—"
    if appt.get("master_id"):
        m = await get_master(appt["master_id"])
        if m:
            master_name = h(m["name"].title())

    service_label = "Xizmat:   " if lang == "uz" else "Услуга:   "
    master_label = "Usta:     " if lang == "uz" else "Мастер:   "
    date_label = "Sana:     " if lang == "uz" else "Дата:     "
    time_label = "Vaqt:     " if lang == "uz" else "Время:    "
    price_label = "Narxi:    " if lang == "uz" else "Цена:     "
    status_label = "Holati:   " if lang == "uz" else "Статус:   "

    text = (
        f"{t('history_visit', lang)}\n\n"
        f"<code>"
        f"{service_label}{h(appt['service_name'])}\n"
        f"{master_label}{master_name}\n"
        f"{date_label}{date_soft(appt['date'], lang)}\n"
        f"{time_label}{appt['time']}\n"
        f"{price_label}{fmt_price(appt['service_price'], lang)}\n"
        f"{status_label}{emoji} {word}"
        f"</code>"
    )

    kb_buttons = []

    if appt["status"] == "scheduled" and not appt.get("paid_at"):
        from utils.payment_ui import resolve_pay_url
        pay_url = await resolve_pay_url(appt)
        if pay_url:
            kb_buttons.append([InlineKeyboardButton(
                text=f"💳 {t('pay_btn', lang)}",
                url=pay_url,
            )])
        else:
            logger.warning(
                "resolve_pay_url=None для appt=%s (status=scheduled, paid_at=None, payment_pay_url=%s)",
                appt_id, appt.get("payment_pay_url"),
            )

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

    # Если запись оплачена — предупреждаем про ручной возврат ДО подтверждения,
    # чтобы клиент успел передумать. Авто-рефанд через API провайдера в MVP
    # не делаем — у первого салона Сабина сама делает refund в дашборде
    # Click/Payme, это минута работы.
    paid_warning = ""
    if appt.get("paid_at"):
        paid_warning = f"\n\n{t('history_cancel_paid_warning', lang)}"

    try:
        await callback.message.edit_text(
            f"{t('history_cancel_confirm_q', lang)}\n\n"
            f"💅 <b>{h(appt['service_name'])}</b>\n"
            f"📅 {date_soft(appt['date'], lang)} · {appt['time']}"
            f"{paid_warning}",
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

    reason_prompt = "<b>Nima bo'ldi?</b>" if lang == "uz" else "<b>Что случилось?</b>"
    try:
        await callback.message.edit_text(
            f"{reason_prompt}\n\n"
            f"💅 <b>{h(appt['service_name'])}</b>\n"
            f"📅 {date_soft(appt['date'], lang)} · {appt['time']}",
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

    # Для оплаченных записей — подсказка админу сделать ручной рефанд.
    # Сабина сама кликнет refund в дашборде Click/Payme. Авто-рефанд
    # через API — FUTURE (нужны права мерчанта, доп. error handling).
    was_paid = bool(appt.get("paid_at"))
    paid_badge = "  💰 <b>БЫЛА ОПЛАЧЕНА</b>" if was_paid else ""
    refund_hint = (
        f"\n\n💸 <i>Сделай возврат вручную в дашборде "
        f"{h(appt.get('payment_provider') or 'провайдера')}.</i>"
        if was_paid else ""
    )

    # Уведомить админа с причиной. С кнопкой закрытия, иначе сообщение
    # висит в чате и отвлекает от админ-панели.
    reason_line = f"\n💬 Причина: {h(reason_label)}" if reason_label else ""
    await broadcast_to_admins(
        callback.bot,
        f"⚠️ <b>Клиент отменил запись</b>{paid_badge}\n\n"
        f"👤 {h(appt['name'])} ({h(appt['phone'])})\n"
        f"📅 {_date_human(appt['date'])}  ·  {appt['time']}\n"
        f"💅 {h(appt['service_name'])}"
        f"{reason_line}"
        f"{refund_hint}",
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

    # Для оплаченных — клиенту строка про возврат (контакт салона из
    # settings.salon_contact если задан). Сабина сама вернёт деньги.
    refund_block = ""
    if was_paid:
        from utils.salon_info import refund_contact_line
        refund_block = (
            f"\n\n{t('refund_needed_intro', lang)}\n"
            f"{await refund_contact_line(lang)}"
        )

    if lang == "uz":
        txt = (
            f"❌ <b>Yozilish bekor qilindi</b>\n\n"
            f"Fikringiz o'zgarsa — biz shu yerdamiz."
            f"{refund_block}"
        )
        btn = "📅 Qayta yozilish"
    else:
        txt = (
            f"❌ <b>Запись отменена</b>\n\n"
            f"Если передумаешь — мы рядом."
            f"{refund_block}"
        )
        btn = "📅 Записаться снова"
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


@router.message(F.text.in_({"мои записи", "mening yozilishlarim", "Mening yozuvlarim", "📋 Мои записи", "📋 Yozuvlarim"}))
async def btn_my_appointments(message: Message, state: FSMContext):
    """Кнопка reply-клавиатуры — сбрасывает FSM и показывает записи клиента (B-стиль)."""
    await state.clear()
    lang = await get_user_lang(message.from_user.id)

    # Один SELECT вместо count+fetch — fetch сам знает len(appts).
    appts = await get_user_appointments_full(message.from_user.id, limit=_FETCH_LIMIT)
    if not appts:
        book_btn = t("btn_book", lang)
        await message.answer(
            t("history_empty", lang),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=f"{ARROW_DO} {book_btn}", callback_data="client_restart"),
            ]]),
            parse_mode="HTML",
        )
        return

    text, kb = await _render_history_b_style(appts, lang)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")
