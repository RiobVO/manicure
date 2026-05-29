"""
Handler-ы callback-кнопок из напоминаний 24h/2h.

Изолированы от основного client-потока: пользователь жмёт кнопку под
напоминанием, мы подтверждаем/отменяем. Никакого FSM. Вынесены из client.py
ради читаемости.
"""
import logging

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from db import (
    get_appointment_by_id,
    cancel_appointment_by_client,
    get_user_lang,
)
from utils.callbacks import parse_callback
from utils.notifications import notify_master, broadcast_to_admins, admin_dismiss_kb
from utils.ui import FLOWER, ARROW_DO, date_soft, h
from utils.i18n import t

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data.startswith("client_confirm_"))
async def cb_client_confirm(callback: CallbackQuery):
    """Клиент подтверждает запись из напоминания."""
    lang = await get_user_lang(callback.from_user.id)
    parts = parse_callback(callback.data, "client_confirm", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer(t("cb_invalid_data", lang), show_alert=True)
        return
    appt_id = int(parts[0])
    appt = await get_appointment_by_id(appt_id)

    if not appt or appt["user_id"] != callback.from_user.id:
        await callback.answer(t("appt_not_found_short", lang), show_alert=True)
        return

    when_label = t("history_when", lang)
    try:
        await callback.message.edit_text(
            f"✅ <b>{t('reminder_we_wait', lang)}</b>\n\n"
            f"<code>"
            f"{when_label}{date_soft(appt['date'], lang)} · {appt['time']}\n"
            f"          {h(appt['service_name'])}"
            f"</code>",
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await callback.answer(t("reminder_confirmed_short", lang))


@router.callback_query(F.data.startswith("client_cancel_"))
async def cb_client_cancel_reminder(callback: CallbackQuery):
    """Клиент отменяет запись из напоминания."""
    lang = await get_user_lang(callback.from_user.id)
    parts = parse_callback(callback.data, "client_cancel", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer(t("cb_invalid_data", lang), show_alert=True)
        return
    appt_id = int(parts[0])
    appt = await get_appointment_by_id(appt_id)

    if not appt or appt["user_id"] != callback.from_user.id:
        await callback.answer(t("appt_not_found_short", lang), show_alert=True)
        return

    success = await cancel_appointment_by_client(appt_id, callback.from_user.id)
    if not success:
        await callback.answer(t("cancel_failed", lang), show_alert=True)
        return

    # Для оплаченных записей — подсказка админу сделать ручной рефанд.
    # Парный путь в client_history.py:507-528 — там же логика. Без этого
    # отмена из напоминания уходила бы как обычная, и возврат легко пропустить.
    was_paid = bool(appt.get("paid_at"))
    paid_badge = "  💰 <b>БЫЛА ОПЛАЧЕНА</b>" if was_paid else ""
    refund_hint = (
        f"\n\n💸 <i>Сделай возврат вручную в дашборде "
        f"{h(appt.get('payment_provider') or 'провайдера')}.</i>"
        if was_paid else ""
    )

    # Уведомить админа. С admin_dismiss_kb — иначе сообщение висит в чате
    # и отвлекает от админ-панели (то же поведение, что в client_history).
    await broadcast_to_admins(
        callback.bot,
        f"⚠️ <b>Клиент отменил запись</b> (из напоминания){paid_badge}\n\n"
        f"👤 {h(appt['name'])} ({h(appt['phone'])})\n"
        f"📅 {appt['date']} в {appt['time']}\n"
        f"💅 {h(appt['service_name'])}"
        f"{refund_hint}",
        reply_markup=admin_dismiss_kb(),
        log_context="client cancellation (reminder)",
    )

    # Уведомление мастера об отмене из напоминания
    if appt.get("master_id"):
        try:
            await notify_master(
                callback.bot, appt["master_id"], "cancelled",
                {"date": appt["date"], "time": appt["time"],
                 "client_name": appt["name"], "service_name": appt["service_name"]},
            )
        except Exception:
            logger.error("Ошибка уведомления мастера об отмене (напоминание)", exc_info=True)

    btn = f"{ARROW_DO} {t('appt_book_again_btn', lang)}"
    try:
        await callback.message.edit_text(
            t("appt_cancelled_full", lang),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=btn, callback_data="client_restart"),
            ]]),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await callback.answer(t("reminder_cancelled_short", lang))
