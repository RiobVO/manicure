"""
Quick-add: ручная запись клиента из дневного вида админ-панели.

Сценарий — владелец на стойке получил звонок «запиши Машу на завтра 15:00»,
открывает «Сегодня»/«Календарь», тапает ➕ — за 5 шагов запись в БД,
мастер получает уведомление.

Шаги FSM (см. AdminQuickAddStates):
  1. enter_name   — имя клиента
  2. enter_phone  — телефон или «Пропустить» (опционально, для напоминаний)
  3. pick_service — услуга из активных в каталоге
  4. pick_master  — мастер или «Любой свободный»
  5. pick_time    — свободный слот из расписания мастера/салона
  6. confirm      — итоговая карточка → «✅ Записать»

Все клавиатуры в keyboards.inline (qadd_*-функции). Все callback_data —
в неймспейсе qadd_* — никаких пересечений с существующими.

Запись пишется в appointments напрямую через create_appointment (с write-
lock и проверкой пересечений), user_id ставим = id админа (нужно чтобы поле
NOT NULL заполнить; админ не получит клиентских уведомлений потому что в
notify_master и broadcast_to_admins он отдельно не пишется как клиент).
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from db import (
    create_appointment, get_active_masters, get_all_settings,
    get_appointments_by_date_full, get_master, get_services,
    get_service_by_id, log_admin_action,
)
from db.appointments import get_booked_times
from db.masters import get_day_schedule_for_master, get_time_blocks_for_master
from db.settings import get_day_schedule, is_day_off, get_time_blocks
from keyboards.inline import (
    admin_cancel_keyboard, day_view_keyboard,
    qadd_confirm_keyboard, qadd_masters_keyboard, qadd_services_keyboard,
    qadd_skip_phone_keyboard, qadd_times_keyboard,
)
from states import AdminQuickAddStates
from utils.admin import (
    IsAdminFilter, deny_access, is_admin_callback, is_admin_message,
)
from utils.callbacks import parse_callback
from utils.notifications import admin_dismiss_kb, broadcast_to_admins, notify_master
from utils.panel import edit_panel, edit_panel_with_callback
from utils.slots import generate_free_slots
from utils.ui import h

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(IsAdminFilter())
router.callback_query.filter(IsAdminFilter())


# ─── helpers ────────────────────────────────────────────────────────────────

def _summary(data: dict) -> str:
    """Заголовок-крошки на верх каждого экрана: что уже выбрано."""
    parts: list[str] = []
    if name := data.get("name"):
        parts.append(f"👤 {h(name)}")
    if phone := data.get("phone"):
        parts.append(f"📞 {h(phone)}")
    if svc_name := data.get("service_name"):
        parts.append(f"💅 {h(svc_name)}")
    if master_name := data.get("master_name"):
        parts.append(f"👨‍🎨 {h(master_name)}")
    return "\n".join(parts)


async def _back_to_day(callback: CallbackQuery, state: FSMContext, date_str: str) -> None:
    """Свернуть FSM и показать день, с которого quick-add стартовал."""
    await state.clear()
    # Локальный импорт чтобы не плодить циклов на старте.
    from handlers.admin_appointments import _build_day_view
    text, markup = await _build_day_view(date_str)
    await edit_panel_with_callback(callback, text, markup)
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass


async def _back_to_day_from_message(message: Message, state: FSMContext, date_str: str) -> None:
    """То же самое, но из текстового сообщения (а не callback)."""
    await state.clear()
    from handlers.admin_appointments import _build_day_view
    text, markup = await _build_day_view(date_str)
    await edit_panel(message.bot, message.chat.id, text, markup)


# ─── 0. Старт: тап ➕ в дневном виде ─────────────────────────────────────────

@router.callback_query(F.data.startswith("qadd_start_"))
async def cb_qadd_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "qadd_start", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    date_str = parts[0]
    await state.clear()
    await state.set_state(AdminQuickAddStates.enter_name)
    await state.update_data(date=date_str)

    text = (
        f"<b>Новая запись на {date_str}</b>\n\n"
        f"Кого записываем?\n"
        f"Введи имя клиента — текстом."
    )
    await edit_panel_with_callback(
        callback, text,
        admin_cancel_keyboard(),  # ↩️ Отмена → admin_cancel (общий хендлер)
        parse_mode="HTML",
    )
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass


# ─── 1. Имя ─────────────────────────────────────────────────────────────────

@router.message(AdminQuickAddStates.enter_name)
async def msg_qadd_name(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    name = (message.text or "").strip()
    data = await state.get_data()
    date_str = data.get("date", "")
    if not name or len(name) > 80:
        await edit_panel(
            message.bot, message.chat.id,
            "⚠️ Имя должно быть от 1 до 80 символов. Попробуй ещё раз:",
            admin_cancel_keyboard(),
        )
        return

    await state.update_data(name=name)
    await state.set_state(AdminQuickAddStates.enter_phone)

    summary = _summary({"name": name})
    text = (
        f"{summary}\n\n"
        f"<b>Телефон</b>\n"
        f"Введи номер или нажми «⏭ Пропустить».\n"
        f"<i>Без телефона напоминания за 24ч/2ч не уйдут.</i>"
    )
    await edit_panel(
        message.bot, message.chat.id, text,
        qadd_skip_phone_keyboard(date_str),
        parse_mode="HTML",
    )


# ─── 2. Телефон (или «Пропустить») ──────────────────────────────────────────

@router.message(AdminQuickAddStates.enter_phone)
async def msg_qadd_phone(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    phone = (message.text or "").strip()
    data = await state.get_data()
    date_str = data.get("date", "")
    # Базовая валидация: разумная длина, иначе админ ткнул не в то место.
    if len(phone) < 5 or len(phone) > 30:
        await edit_panel(
            message.bot, message.chat.id,
            "⚠️ Телефон коротковат или слишком длинный. Введи нормальный номер "
            "или нажми «⏭ Пропустить».",
            qadd_skip_phone_keyboard(date_str),
        )
        return

    await state.update_data(phone=phone)
    await _show_services_step(message.bot, message.chat.id, state)


@router.callback_query(AdminQuickAddStates.enter_phone, F.data == "qadd_skip_phone")
async def cb_qadd_skip_phone(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    # Пометка — телефон опущен. В БД пишем «—» (поле NOT NULL).
    await state.update_data(phone="—", phone_skipped=True)
    await _show_services_step(callback.bot, callback.message.chat.id, state)
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass


# ─── 3. Услуга ──────────────────────────────────────────────────────────────

async def _show_services_step(bot, chat_id: int, state: FSMContext) -> None:
    """Рендер шага выбора услуги. Вызываем после ввода телефона ИЛИ
    после нажатия «Пропустить» — общий код."""
    data = await state.get_data()
    date_str = data.get("date", "")
    services = await get_services(active_only=True)
    if not services:
        # Деградированный путь: без услуг записать нельзя. Возвращаем
        # на день с подсказкой, FSM сбрасываем.
        await edit_panel(
            bot, chat_id,
            "⚠️ В каталоге нет активных услуг. Сначала добавь хотя бы одну "
            "в «💅 Услуги», потом записывай клиентов.",
            None,
        )
        await state.clear()
        return

    await state.set_state(AdminQuickAddStates.pick_service)

    summary = _summary(data)
    text = (
        f"{summary}\n\n"
        f"<b>Выбери услугу:</b>"
    )
    await edit_panel(bot, chat_id, text, qadd_services_keyboard(services, date_str), parse_mode="HTML")


@router.callback_query(AdminQuickAddStates.pick_service, F.data.startswith("qadd_svc_"))
async def cb_qadd_pick_service(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "qadd_svc", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    service_id = int(parts[0])
    service = await get_service_by_id(service_id)
    if not service or not service.get("is_active"):
        await callback.answer("Эта услуга больше не доступна.", show_alert=True)
        return

    await state.update_data(
        service_id=service["id"],
        service_name=service["name"],
        service_duration=service["duration"],
        service_price=service["price"],
    )

    masters = await get_active_masters()
    data = await state.get_data()
    date_str = data.get("date", "")

    if not masters:
        # Совсем без мастеров — записываем без привязки (master_id=None),
        # сразу на шаг «время». Расписание берётся из weekly_schedule.
        await state.update_data(master_id=None, master_name=None)
        await _show_times_step(callback.bot, callback.message.chat.id, state)
        try:
            await callback.answer()
        except TelegramBadRequest:
            pass
        return

    await state.set_state(AdminQuickAddStates.pick_master)
    summary = _summary(data)
    text = f"{summary}\n\n<b>Кто будет работать?</b>"
    await edit_panel(
        callback.bot, callback.message.chat.id, text,
        qadd_masters_keyboard(masters, date_str),
        parse_mode="HTML",
    )
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass


# ─── 4. Мастер ──────────────────────────────────────────────────────────────

@router.callback_query(AdminQuickAddStates.pick_master, F.data == "qadd_master_any")
async def cb_qadd_master_any(callback: CallbackQuery, state: FSMContext):
    """Опция «Любой свободный» — пишем без привязки к мастеру.
    Запись попадёт в общую очередь, расписание берётся из weekly_schedule."""
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    await state.update_data(master_id=None, master_name=None)
    await _show_times_step(callback.bot, callback.message.chat.id, state)
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass


@router.callback_query(AdminQuickAddStates.pick_master, F.data.startswith("qadd_master_"))
async def cb_qadd_pick_master(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "qadd_master", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    try:
        master_id = int(parts[0])
    except ValueError:
        await callback.answer()
        return
    master = await get_master(master_id)
    if not master:
        await callback.answer("Этого мастера больше нет в списке.", show_alert=True)
        return
    await state.update_data(master_id=master["id"], master_name=master["name"])
    await _show_times_step(callback.bot, callback.message.chat.id, state)
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass


# ─── 5. Время ───────────────────────────────────────────────────────────────

async def _show_times_step(bot, chat_id: int, state: FSMContext) -> None:
    """Считаем свободные слоты по тем же правилам что booking-флоу клиента:
    рабочие часы мастера/салона минус booked + минус blocked, шаг slot_step."""
    data = await state.get_data()
    date_str = data["date"]
    duration = data["service_duration"]
    master_id = data.get("master_id")

    # Рабочие часы и блокировки — отдельные пути для master и для салона.
    if master_id:
        day_sched = await get_day_schedule_for_master(master_id, date_str)
        if day_sched is None:
            await edit_panel(
                bot, chat_id,
                f"{_summary(data)}\n\n"
                f"⚠️ У мастера в этот день выходной. Выбери другого "
                f"мастера или другую дату.",
                qadd_masters_keyboard(await get_active_masters(), date_str),
                parse_mode="HTML",
            )
            await state.set_state(AdminQuickAddStates.pick_master)
            return
        blocked = await get_time_blocks_for_master(master_id, date_str)
    else:
        if await is_day_off(date_str):
            await edit_panel(
                bot, chat_id,
                f"{_summary(data)}\n\n⚠️ Этот день полностью заблокирован.",
                None,
            )
            await state.clear()
            return
        day_sched = await get_day_schedule(date_str)
        if day_sched is None:
            await edit_panel(
                bot, chat_id,
                f"{_summary(data)}\n\n⚠️ Салон в этот день недели не работает.",
                None,
            )
            await state.clear()
            return
        blocked = await get_time_blocks(date_str)

    work_start, work_end = day_sched
    slot_step = int((await get_all_settings()).get("slot_step", 30))
    booked = await get_booked_times(date_str, master_id)
    free = generate_free_slots(
        booked, duration, date_str, work_start, work_end, slot_step, blocked,
    )

    if not free:
        msg = (
            f"{_summary(data)}\n\n"
            f"⚠️ На <b>{date_str}</b> свободных слотов нет. "
            f"Выбери другого мастера или другую дату."
        )
        # Возвращаем на выбор мастера — это самый дешёвый способ перепрыгнуть.
        masters = await get_active_masters()
        await edit_panel(
            bot, chat_id, msg,
            qadd_masters_keyboard(masters, date_str) if masters else None,
            parse_mode="HTML",
        )
        if masters:
            await state.set_state(AdminQuickAddStates.pick_master)
        else:
            await state.clear()
        return

    await state.set_state(AdminQuickAddStates.pick_time)
    text = (
        f"{_summary(data)}\n\n"
        f"<b>Свободное время на {date_str}:</b>"
    )
    await edit_panel(
        bot, chat_id, text,
        qadd_times_keyboard(free, date_str),
        parse_mode="HTML",
    )


@router.callback_query(AdminQuickAddStates.pick_time, F.data.startswith("qadd_time_"))
async def cb_qadd_pick_time(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "qadd_time", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    time_str = parts[0]
    await state.update_data(time=time_str)
    await state.set_state(AdminQuickAddStates.confirm)

    data = await state.get_data()
    date_str = data["date"]
    phone_line = (
        f"\n📞 {h(data['phone'])}"
        if data.get("phone") and data["phone"] != "—"
        else "\n<i>📞 без телефона — напоминания не уйдут</i>"
    )
    text = (
        f"<b>Записать?</b>\n\n"
        f"👤 {h(data['name'])}"
        f"{phone_line}\n"
        f"💅 {h(data['service_name'])} · {data['service_price']:,} сум"
        .replace(",", " ") +
        f" · {data['service_duration']} мин\n"
        f"👨‍🎨 {h(data.get('master_name') or 'Любой свободный')}\n"
        f"📅 {date_str} в <b>{time_str}</b>"
    )
    await edit_panel_with_callback(
        callback, text,
        qadd_confirm_keyboard(date_str),
        parse_mode="HTML",
    )
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass


# ─── 6. Подтверждение → создание записи ─────────────────────────────────────

@router.callback_query(AdminQuickAddStates.confirm, F.data == "qadd_confirm")
async def cb_qadd_confirm(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    data = await state.get_data()
    date_str = data["date"]
    admin_id = callback.from_user.id

    # user_id=0 для ручных записей — это sentinel «нет реального telegram-клиента».
    # Если поставить admin_id, то при пометке записи 'completed' бот пришлёт
    # ему же запрос на отзыв («оцените визит»), напоминания за 24ч/2ч тоже
    # уйдут админу (он же и user_id записи). 0 — невалидный telegram chat_id,
    # send_message(0, …) молча отвалится TelegramBadRequest, который везде
    # ловится try/except. Поле в схеме INTEGER NOT NULL, 0 проходит.
    try:
        appt_id = await create_appointment(
            user_id=0,
            name=data["name"],
            phone=data["phone"],
            service_id=data["service_id"],
            service_name=data["service_name"],
            service_duration=data["service_duration"],
            service_price=data["service_price"],
            date=date_str,
            time=data["time"],
            master_id=data.get("master_id"),
        )
    except ValueError as exc:
        # Слот успели занять (race с клиентом или другим админом).
        # Бросаем обратно на выбор времени.
        logger.info("qadd: слот занят, %s", exc)
        await callback.answer(
            "Этот слот уже заняли. Выбери другое время.",
            show_alert=True,
        )
        await _show_times_step(callback.bot, callback.message.chat.id, state)
        return
    except Exception:
        logger.exception("qadd: create_appointment failed")
        await callback.answer(
            "Не получилось создать запись. Попробуй ещё раз.",
            show_alert=True,
        )
        return

    # Аудит-лог в фон не нужно — он быстрый, всё ок и без _fire.
    try:
        await log_admin_action(
            admin_id=admin_id,
            action="quick_add",
            target_type="appointment",
            target_id=appt_id,
            details=f"{data['name']} — {data['service_name']} ({date_str} {data['time']})",
        )
    except Exception:
        logger.warning("qadd: log_admin_action failed", exc_info=True)

    # Уведомление мастеру (если выбран). Без _fire — редкая операция.
    master_id = data.get("master_id")
    if master_id:
        try:
            await notify_master(
                callback.bot, master_id, "new_booking",
                {
                    "date": date_str,
                    "time": data["time"],
                    "client_name": data["name"],
                    "service_name": data["service_name"],
                },
            )
        except Exception:
            logger.warning("qadd: notify_master failed", exc_info=True)

    # Бродкаст всем админам — для ауди­та. Тот, кто записал, тоже получит
    # копию (admin_dismiss_kb позволяет убрать одним кликом).
    # Строку телефона показываем только если он реально введён —
    # «📞 —» выглядит как недоделка, лучше просто пропустить строку.
    phone_line = f"\n📞 {h(data['phone'])}" if data.get("phone") and data["phone"] != "—" else ""
    try:
        await broadcast_to_admins(
            callback.bot,
            f"➕ <b>Запись создана вручную</b>\n"
            f"{date_str} в <b>{data['time']}</b>\n"
            f"💅 {h(data['service_name'])} — {h(data['name'])}"
            f"{phone_line}",
            reply_markup=admin_dismiss_kb(),
            log_context="qadd notify",
        )
    except Exception:
        logger.warning("qadd: broadcast failed", exc_info=True)

    await state.clear()
    # Возврат на день — чтобы новая запись появилась в списке сразу.
    from handlers.admin_appointments import _build_day_view
    text, markup = await _build_day_view(date_str)
    await edit_panel_with_callback(callback, text, markup)
    try:
        await callback.answer("✅ Записано")
    except TelegramBadRequest:
        pass


# ─── Отмена с любого шага ───────────────────────────────────────────────────

@router.callback_query(F.data.startswith("qadd_cancel_"))
async def cb_qadd_cancel(callback: CallbackQuery, state: FSMContext):
    """Универсальная отмена с любого шага quick-add. Возвращает на день,
    с которого начали — date_str закодирован в callback_data."""
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "qadd_cancel", 1)
    date_str = parts[0] if parts else None
    if not date_str:
        # Защита от мусора в callback — лучше уйти на пустую панель чем упасть.
        await state.clear()
        try:
            await callback.answer()
        except TelegramBadRequest:
            pass
        return
    await _back_to_day(callback, state, date_str)
