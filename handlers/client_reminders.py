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
)
from utils.callbacks import parse_callback
from utils.notifications import notify_master, broadcast_to_admins
from utils.ui import FLOWER, ARROW_DO, date_soft, h

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data.startswith("client_confirm_"))
async def cb_client_confirm(callback: CallbackQuery):
    """Клиент подтверждает запись из напоминания."""
    parts = parse_callback(callback.data, "client_confirm", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer("Неверный формат данных.", show_alert=True)
        return
    appt_id = int(parts[0])
    appt = await get_appointment_by_id(appt_id)

    if not appt or appt["user_id"] != callback.from_user.id:
        await callback.answer("Запись не найдена.", show_alert=True)
        return

    try:
        await callback.message.edit_text(
            f"{FLOWER}\n\n"
            f"<b><i>ждём тебя.</i></b>\n\n"
            f"<blockquote>"
            f"<b>{h(appt['service_name'].lower())}</b>\n"
            f"<i>когда</i>  <code>{date_soft(appt['date'])} · {appt['time']}</code>"
            f"</blockquote>",
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await callback.answer("Запись подтверждена!")


@router.callback_query(F.data.startswith("client_cancel_"))
async def cb_client_cancel_reminder(callback: CallbackQuery):
    """Клиент отменяет запись из напоминания."""
    parts = parse_callback(callback.data, "client_cancel", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer("Неверный формат данных.", show_alert=True)
        return
    appt_id = int(parts[0])
    appt = await get_appointment_by_id(appt_id)

    if not appt or appt["user_id"] != callback.from_user.id:
        await callback.answer("Запись не найдена.", show_alert=True)
        return

    success = await cancel_appointment_by_client(appt_id, callback.from_user.id)
    if not success:
        await callback.answer("Не удалось отменить запись.", show_alert=True)
        return

    # Уведомить админа
    await broadcast_to_admins(
        callback.bot,
        f"⚠️ <b>Клиент отменил запись</b> (из напоминания)\n\n"
        f"👤 {h(appt['name'])} ({h(appt['phone'])})\n"
        f"📅 {appt['date']} в {appt['time']}\n"
        f"💅 {h(appt['service_name'])}",
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

    try:
        await callback.message.edit_text(
            f"<i>запись ушла.</i>\n\n"
            f"<i>если передумаешь — мы рядом.</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=f"{ARROW_DO} записаться снова", callback_data="client_restart"),
            ]]),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await callback.answer("Запись отменена")
