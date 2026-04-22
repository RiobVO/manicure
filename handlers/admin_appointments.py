import asyncio
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from datetime import datetime, timedelta

from utils.timezone import now_local


# Глобальный set фоновых задач — не даём GC убить их до завершения.
# Уведомления клиенту/мастеру/broadcast уходят fire-and-forget чтобы
# админ не ждал 3 секунды синхронного цикла из 5 Telegram API-вызовов.
_bg_tasks: set[asyncio.Task] = set()


def _fire(coro, context: str) -> None:
    """Запустить фоновую задачу, залогировать ошибку при падении."""
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)

    def _log(t: asyncio.Task) -> None:
        exc = t.exception()
        if exc is not None:
            logger.warning("bg task '%s' failed: %s", context, exc)

    task.add_done_callback(_log)

from states import AdminStates
from config import ADMIN_IDS
from db import (
    get_appointments_by_date_full, get_appointment_by_id,
    update_appointment_status, reschedule_appointment,
    get_booked_times, get_time_blocks, is_day_off, get_all_settings,
    log_admin_action, _price_fmt, get_day_schedule,
    get_review_by_appointment, get_master,
    get_day_schedule_for_master, get_time_blocks_for_master,
)
from keyboards.inline import (
    admin_keyboard, day_view_keyboard, appointment_actions_keyboard,
    cancel_confirm_keyboard, reschedule_dates_keyboard, reschedule_times_keyboard,
    calendar_keyboard, review_rating_keyboard,
)
from utils.slots import generate_free_slots
from utils.admin import STATUS_LABEL, is_admin_callback, deny_access, IsAdminFilter
from utils.callbacks import parse_callback
from utils.notifications import notify_master, notify_client
from utils.panel import edit_panel_with_callback, edit_panel, get_panel_msg_id, clear_panel_msg_id
from utils.ui import h

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(IsAdminFilter())
router.callback_query.filter(IsAdminFilter())

_STATUS_ICON = {"completed": "✅", "no_show": "🚫", "cancelled": "❌"}


# ─── HELPERS ─────────────────────────────────────────────────────────────────

async def _build_day_view(date_str: str) -> tuple[str, object]:
    """Возвращает (text, markup) для дневного вида."""
    all_appts = await get_appointments_by_date_full(date_str)
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        label = dt.strftime("%d.%m.%Y")
    except ValueError:
        label = date_str

    if not all_appts:
        return f"📭 На {label} записей нет.", None

    scheduled = [a for a in all_appts if a["status"] == "scheduled"]
    archived  = [a for a in all_appts if a["status"] != "scheduled"]
    lines = []
    if scheduled:
        lines.append(f"📅 {label}  •  🟢 В очереди: {len(scheduled)}")
        for a in scheduled:
            master_line = f"\n   👨\u200d🎨 {a['master_name']}" if a.get("master_name") else ""
            lines.append(
                f"\n🕐 {a['time']} — {a['name']}\n"
                f"   📞 {a['phone']}\n"
                f"   💅 {a['service_name']}"
                f"{master_line}"
            )
    else:
        lines.append(f"📅 {label}  •  Активных записей нет")
    if archived:
        parts = [
            f"{_STATUS_ICON.get(a['status'], '❓')} {a['time']} {a['name'].split()[0]}"
            for a in archived
        ]
        lines.append(f"\n📁 История: {' | '.join(parts)}")
    return "\n".join(lines), day_view_keyboard(scheduled, date_str)


async def show_day_view(callback: CallbackQuery, date_str: str) -> None:
    """Дневной вид — редактирует панель или создаёт новую."""
    text, markup = await _build_day_view(date_str)
    await edit_panel_with_callback(callback, text, markup)
    await callback.answer()


# ─── СЕГОДНЯ / ЗАВТРА ────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_today")
async def cb_today(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    today = now_local().strftime("%Y-%m-%d")
    await show_day_view(callback, today)


@router.callback_query(F.data == "admin_tomorrow")
async def cb_tomorrow(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    tomorrow = (now_local() + timedelta(days=1)).strftime("%Y-%m-%d")
    await show_day_view(callback, tomorrow)


# ─── КАЛЕНДАРЬ ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_cal")
async def cb_admin_cal(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    now = now_local()
    await edit_panel(
        callback.bot, callback.message.chat.id,
        "🗓 Выберите дату:",
        calendar_keyboard(now.year, now.month),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cal_prev_"))
async def cb_cal_prev(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "cal_prev", 2)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    year, month = parts
    text = callback.message.text or "🗓 Выберите дату:"
    await edit_panel(callback.bot, callback.message.chat.id, text, calendar_keyboard(int(year), int(month)))
    await callback.answer()


@router.callback_query(F.data.startswith("cal_next_"))
async def cb_cal_next(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "cal_next", 2)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    year, month = parts
    text = callback.message.text or "🗓 Выберите дату:"
    await edit_panel(callback.bot, callback.message.chat.id, text, calendar_keyboard(int(year), int(month)))
    await callback.answer()


@router.callback_query(F.data.startswith("cal_day_"))
async def cb_cal_day(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return

    # Два формата: cal_day_back_YYYY-MM-DD (2 части) и cal_day_YEAR_MONTH_DAY (3 части)
    back_parts = parse_callback(callback.data, "cal_day_back", 1)
    if back_parts:
        date_str = back_parts[0]
    else:
        day_parts = parse_callback(callback.data, "cal_day", 3)
        if not day_parts:
            logger.warning("Некорректный callback: %s", callback.data)
            await callback.answer()
            return
        year, month, day = int(day_parts[0]), int(day_parts[1]), int(day_parts[2])
        date_str = f"{year}-{month:02d}-{day:02d}"

    await show_day_view(callback, date_str)


@router.callback_query(F.data == "cal_noop")
async def cb_cal_noop(callback: CallbackQuery):
    await callback.answer()


# ─── СТАТУС ЗАПИСИ ───────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("appt_status_"))
async def cb_appt_status(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return

    parts = parse_callback(callback.data, "appt_status", 2)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    appt_id = int(parts[0])
    status = parts[1]

    appt = await get_appointment_by_id(appt_id)
    await update_appointment_status(appt_id, status)

    # Лог действия — в фон.
    if appt:
        _fire(
            log_admin_action(
                admin_id=callback.from_user.id,
                action=f"status_{status}",
                target_type="appointment",
                target_id=appt_id,
                details=f"{appt['name']} — {appt['service_name']} ({appt['date']} {appt['time']})",
            ),
            context=f"log status_{status}",
        )

    label = STATUS_LABEL.get(status, status)
    await callback.answer(f"Статус обновлён: {label}", show_alert=False)

    # Запрос отзыва клиенту при завершении визита — в фон.
    if status == "completed" and appt:
        async def _send_review_request() -> None:
            existing_review = await get_review_by_appointment(appt_id)
            if existing_review:
                return
            from db import get_user_lang
            from utils.i18n import t
            client_lang = await get_user_lang(appt["user_id"])
            try:
                await callback.bot.send_message(
                    appt["user_id"],
                    t("review_after_visit_title", client_lang, service=h(appt['service_name'].lower())),
                    reply_markup=review_rating_keyboard(appt_id),
                    parse_mode="HTML",
                )
            except Exception:
                logger.warning("Не удалось отправить запрос отзыва user_id=%s", appt["user_id"])

        _fire(_send_review_request(), context="send review request")

    # Уведомление мастеру об изменении статуса — в фон.
    if appt and appt.get("master_id"):
        async def _notify_master_status() -> None:
            _master = await get_master(appt["master_id"])
            if not (_master and _master.get("user_id") and _master["user_id"] not in ADMIN_IDS):
                return
            _status_text = {"completed": "✅ Выполнено", "no_show": "🚫 Не пришёл", "cancelled": "❌ Отменено"}
            try:
                await callback.bot.send_message(
                    _master["user_id"],
                    f"📋 <b>Статус записи изменён</b>\n\n"
                    f"👤 {h(appt['name'])}\n"
                    f"📅 {appt['date']} в {appt['time']}\n"
                    f"💅 {h(appt['service_name'])}\n\n"
                    f"Новый статус: {_status_text.get(status, status)}",
                    parse_mode="HTML",
                )
            except Exception:
                logger.warning("Не удалось уведомить мастера user_id=%s", _master["user_id"])

        _fire(_notify_master_status(), context="notify master status")

    # Уведомление клиенту об изменении статуса — в фон.
    if appt and status != "completed":
        _fire(
            notify_client(
                callback.bot, appt["user_id"], "status_changed",
                {"date": appt["date"], "time": appt["time"], "status": label},
            ),
            context="notify client status",
        )

    # UI админа — единственное await, который админ ждёт синхронно.
    if appt:
        from utils.payment_ui import payment_pill
        text = (
            f"📋 Запись #{appt_id}\n\n"
            f"⏰ {appt['time']} — {appt['name']}\n"
            f"📞 {appt['phone']}\n"
            f"💅 {appt['service_name']}\n"
            f"📌 {label}"
            f"{payment_pill(appt)}"
        )
        # status, а не appt["status"] — appt содержит старый статус до update_appointment_status
        await edit_panel_with_callback(
            callback, text,
            appointment_actions_keyboard(
                appt_id, appt["date"], status,
                paid=bool(appt.get("paid_at")),
            ),
        )


# ─── ОТМЕНА ЗАПИСИ ───────────────────────────────────────────────────────────

@router.callback_query(
    F.data.startswith("appt_cancel_")
    & ~F.data.startswith("appt_cancel_confirm_")
    & ~F.data.startswith("appt_cancel_abort_")
)
async def cb_appt_cancel(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return

    parts = parse_callback(callback.data, "appt_cancel", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    appt_id = int(parts[0])
    appt = await get_appointment_by_id(appt_id)
    if not appt:
        await callback.answer("Запись не найдена.", show_alert=True)
        return

    text = (
        f"❓ Отменить запись?\n\n"
        f"👤 {appt['name']}\n"
        f"📅 {appt['date']} в {appt['time']}\n"
        f"💅 {appt['service_name']}"
    )
    await edit_panel_with_callback(callback, text, cancel_confirm_keyboard(appt_id))
    await callback.answer()


@router.callback_query(F.data.startswith("appt_cancel_confirm_"))
async def cb_appt_cancel_confirm(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return

    parts = parse_callback(callback.data, "appt_cancel_confirm", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    appt_id = int(parts[0])
    appt = await get_appointment_by_id(appt_id)
    if not appt:
        await callback.answer("Запись не найдена.", show_alert=True)
        return

    # Критичный путь: обновить БД + UI админа. Всё что касается
    # уведомлений третьим лицам (клиент, мастер, другие админы) уходит
    # в фон через _fire — админу нет смысла ждать 3 секунды пока все
    # send_message последовательно сходят в Telegram API. В случае
    # ошибки уведомления — warning в лог, UX админа не страдает.
    await update_appointment_status(appt_id, "cancelled")

    # Лог действия — в фон (аудит не блокирует UX).
    _fire(
        log_admin_action(
            admin_id=callback.from_user.id,
            action="cancel",
            target_type="appointment",
            target_id=appt_id,
            details=f"{appt['name']} — {appt['service_name']} ({appt['date']} {appt['time']})",
        ),
        context="log cancel",
    )

    # Refund-алерт админам — в фон.
    if appt.get("paid_at"):
        from utils.notifications import admin_dismiss_kb, broadcast_to_admins
        price = appt.get("service_price", 0)
        refund_text = (
            f"🔴 <b>Нужен возврат</b>\n"
            f"Запись #{appt_id} отменена после оплаты.\n"
            f"Клиент: {h(appt['name'])}\n"
            f"Сумма: {price:,} UZS\n".replace(",", " ") +
            f"Провайдер: <code>{appt.get('payment_provider') or '—'}</code>\n"
            f"Инвойс: <code>{appt.get('payment_invoice_id') or '—'}</code>\n\n"
            f"<i>сделай возврат вручную в дашборде провайдера.</i>"
        )
        _fire(
            broadcast_to_admins(
                callback.bot, refund_text,
                reply_markup=admin_dismiss_kb("✅ Возврат сделан"),
                log_context="refund needed",
            ),
            context="refund alert",
        )

    # Уведомление клиенту — в фон (собираем сообщение здесь, чтобы
    # не тянуть get_user_lang / refund_contact_line в синхронный путь).
    async def _notify_client_cancelled() -> None:
        from db import get_user_lang
        from utils.i18n import t
        client_lang = await get_user_lang(appt["user_id"])
        refund_block = ""
        if appt.get("paid_at"):
            from utils.salon_info import refund_contact_line
            refund_block = (
                "\n\n" + t("refund_needed_intro", client_lang)
                + "\n" + await refund_contact_line(client_lang)
            )
        if client_lang == "uz":
            cancel_msg = (
                f"❌ Yozilishingiz usta tomonidan bekor qilindi.\n\n"
                f"📅 {appt['date']} · {appt['time']}\n"
                f"💅 {appt['service_name']}\n\n"
                f"Boshqa vaqtga yozilish uchun usta bilan bog'laning."
            )
        else:
            cancel_msg = (
                f"❌ Ваша запись отменена мастером.\n\n"
                f"📅 {appt['date']} в {appt['time']}\n"
                f"💅 {appt['service_name']}\n\n"
                f"Пожалуйста, свяжитесь с мастером для записи на другое время."
            )
        try:
            await callback.bot.send_message(appt["user_id"], cancel_msg + refund_block)
        except Exception:
            logger.warning(
                "Could not notify user_id=%s about cancellation",
                appt["user_id"],
            )

    _fire(_notify_client_cancelled(), context="notify client cancelled")

    # Уведомление мастеру об отмене — в фон.
    if appt.get("master_id"):
        async def _notify_master_cancelled() -> None:
            _master = await get_master(appt["master_id"])
            if not (_master and _master.get("user_id") and _master["user_id"] not in ADMIN_IDS):
                return
            try:
                await callback.bot.send_message(
                    _master["user_id"],
                    f"📋 <b>Статус записи изменён</b>\n\n"
                    f"👤 {h(appt['name'])}\n"
                    f"📅 {appt['date']} в {appt['time']}\n"
                    f"💅 {h(appt['service_name'])}\n\n"
                    f"Новый статус: ❌ Отменено",
                    parse_mode="HTML",
                )
            except Exception:
                logger.warning("Не удалось уведомить мастера user_id=%s", _master["user_id"])

        _fire(_notify_master_cancelled(), context="notify master cancelled")

    # UI админа — единственное await, который клиент ждёт.
    await edit_panel_with_callback(
        callback, "✅ Запись отменена. Уведомление клиенту отправлено.", None,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("appt_cancel_abort_"))
async def cb_appt_cancel_abort(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return

    parts = parse_callback(callback.data, "appt_cancel_abort", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    appt_id = int(parts[0])
    appt = await get_appointment_by_id(appt_id)
    if appt:
        status = STATUS_LABEL.get(appt["status"], appt["status"])
        text = (
            f"📋 Запись #{appt_id}\n\n"
            f"⏰ {appt['time']} — {appt['name']}\n"
            f"📞 {appt['phone']}\n"
            f"💅 {appt['service_name']}\n"
            f"📌 {status}"
        )
        await edit_panel_with_callback(
            callback, text,
            appointment_actions_keyboard(
                appt_id, appt["date"], appt["status"],
                paid=bool(appt.get("paid_at")),
            ),
        )
    await callback.answer()


# ─── РУЧНАЯ ПОМЕТКА «ОПЛАЧЕНО» ───────────────────────────────────────────────

@router.callback_query(F.data.startswith("appt_mark_paid_"))
async def cb_appt_mark_paid(callback: CallbackQuery):
    """
    Резервный путь, когда реальный webhook Click/Payme не дошёл (DNS,
    упавший туннель, рестарт бота в момент платежа). Админ увидел что
    клиент оплатил, но в боте всё ещё «⏳ Ждёт оплаты» — жмёт кнопку.
    """
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "appt_mark_paid", 1)
    if not parts:
        await callback.answer()
        return
    appt_id = int(parts[0])
    from db.payments import mark_paid_manual, get_payment_state
    ok = await mark_paid_manual(appt_id)
    if not ok:
        await callback.answer("Запись уже оплачена или не найдена.", show_alert=True)
        return

    # Удалить pay-сообщение у клиента — та же логика что в webhook _notify_paid:
    # url-кнопка в старом сообщении продолжит работать, если её не убрать,
    # и клиент может случайно инициировать второй платёж. Ошибку глотаем —
    # 48-часовой лимит Telegram на delete, сообщение могло устареть.
    state = await get_payment_state(appt_id)
    if state and state.get("payment_message_id"):
        try:
            await callback.bot.delete_message(
                chat_id=state["user_id"],
                message_id=state["payment_message_id"],
            )
        except Exception as exc:
            logger.debug(
                "не удалил pay-сообщение при ручной оплате appt=%s: %s",
                appt_id, exc,
            )

    try:
        await log_admin_action(
            admin_id=callback.from_user.id,
            action="mark_paid_manual",
            target_type="appointment",
            target_id=appt_id,
        )
    except Exception:
        logger.warning("не удалось записать лог ручной оплаты appt=%s", appt_id)

    await callback.answer("✅ Помечено оплаченной", show_alert=False)

    # Обновляем карточку — перерисовываем с новым pill'ом.
    appt = await get_appointment_by_id(appt_id)
    if not appt:
        return
    from utils.payment_ui import payment_pill
    label = STATUS_LABEL.get(appt["status"], appt["status"])
    text = (
        f"📋 Запись #{appt_id}\n\n"
        f"⏰ {appt['time']} — {appt['name']}\n"
        f"📞 {appt['phone']}\n"
        f"💅 {appt['service_name']}\n"
        f"📌 {label}"
        f"{payment_pill(appt)}"
    )
    await edit_panel_with_callback(
        callback, text,
        appointment_actions_keyboard(
            appt_id, appt["date"], appt["status"],
            paid=bool(appt.get("paid_at")),
        ),
    )


# ─── ПЕРЕНОС ЗАПИСИ ──────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("appt_reschedule_"))
async def cb_appt_reschedule(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return

    parts = parse_callback(callback.data, "appt_reschedule", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    appt_id = int(parts[0])
    await state.set_state(AdminStates.reschedule_pick_date)

    await edit_panel_with_callback(callback, "🔄 Выберите новую дату для переноса:", reschedule_dates_keyboard(appt_id))
    await callback.answer()


@router.callback_query(AdminStates.reschedule_pick_date, F.data.startswith("rs_date_"))
async def cb_reschedule_date(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return

    parts = parse_callback(callback.data, "rs_date", 2)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    appt_id = int(parts[0])
    date_str = parts[1]

    appt = await get_appointment_by_id(appt_id)
    if not appt:
        await callback.answer("Запись не найдена.", show_alert=True)
        await state.clear()
        return

    master_id = appt.get("master_id")

    # Проверка выходного дня с учётом мастера
    if master_id:
        if await get_day_schedule_for_master(master_id, date_str) is None:
            await callback.answer("Этот день — выходной или заблокирован.", show_alert=True)
            return
    else:
        if await is_day_off(date_str):
            await callback.answer("Этот день заблокирован. Выберите другую дату.", show_alert=True)
            return

    # Рабочие часы — по мастеру если есть
    if master_id:
        day_sched = await get_day_schedule_for_master(master_id, date_str)
    else:
        day_sched = await get_day_schedule(date_str)
    # Если день — выходной по расписанию, для переноса (действие админа)
    # используем полный диапазон 9–19, чтобы не блокировать перенос.
    work_start, work_end = day_sched if day_sched else (9, 19)
    slot_step = int((await get_all_settings()).get("slot_step", 30))

    booked = await get_booked_times(date_str, master_id)
    booked = [(t, d) for t, d in booked if not (t == appt["time"] and date_str == appt["date"])]
    if master_id:
        blocked_ranges = await get_time_blocks_for_master(master_id, date_str)
    else:
        blocked_ranges = await get_time_blocks(date_str)

    free_slots = generate_free_slots(
        booked, appt["service_duration"], date_str,
        work_start, work_end, slot_step, blocked_ranges,
    )

    if not free_slots:
        await callback.answer("На этот день нет свободных слотов.", show_alert=True)
        return

    await edit_panel_with_callback(
        callback,
        f"🔄 Перенос на {date_str}\nВыберите время:",
        reschedule_times_keyboard(appt_id, date_str, free_slots),
    )
    await state.set_state(AdminStates.reschedule_pick_time)
    await callback.answer()


@router.callback_query(AdminStates.reschedule_pick_time, F.data.startswith("rs_time_"))
async def cb_reschedule_time(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return

    parts = parse_callback(callback.data, "rs_time", 3)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    appt_id = int(parts[0])
    new_date = parts[1]
    new_time = parts[2]

    appt = await get_appointment_by_id(appt_id)
    if not appt:
        await callback.answer("Запись не найдена.", show_alert=True)
        await state.clear()
        return

    try:
        await reschedule_appointment(
            appt_id, new_date, new_time,
            service_duration=appt["service_duration"],
            master_id=appt.get("master_id"),
        )
    except ValueError:
        await callback.answer("⚠️ Этот слот уже занят!", show_alert=True)
        return

    await log_admin_action(
        admin_id=callback.from_user.id,
        action="reschedule",
        target_type="appointment",
        target_id=appt_id,
        details=f"{appt['name']} — {appt['service_name']}: {appt['date']} {appt['time']} → {new_date} {new_time}",
    )

    # Уведомление клиенту о переносе
    notified = False
    try:
        await callback.bot.send_message(
            appt["user_id"],
            f"🔄 Ваша запись перенесена!\n\n"
            f"📅 {new_date} в {new_time}\n"
            f"💅 {appt['service_name']}\n\n"
            f"Ждём вас! 🙂",
        )
        notified = True
    except Exception:
        logger.warning("Could not notify user_id=%s about reschedule", appt["user_id"])

    # Уведомление мастеру о переносе
    if appt.get("master_id"):
        _master = await get_master(appt["master_id"])
        if _master and _master.get("user_id") and _master["user_id"] not in ADMIN_IDS:
            try:
                await callback.bot.send_message(
                    _master["user_id"],
                    f"🔄 <b>Запись перенесена</b>\n\n"
                    f"👤 {h(appt['name'])}\n"
                    f"💅 {h(appt['service_name'])}\n"
                    f"📅 Новая дата: {new_date} в {new_time}",
                    parse_mode="HTML",
                )
            except Exception:
                logger.warning("Не удалось уведомить мастера о переносе user_id=%s", _master["user_id"])

    result = "Клиент уведомлён." if notified else "Клиент не уведомлён (заблокировал бота)."
    await edit_panel_with_callback(callback, f"✅ Запись перенесена на {new_date} в {new_time}. {result}", None)
    await state.clear()
    await callback.answer()
