"""
Админский редактор per-master расписания.

Зеркало handlers/admin_settings.py (редактор глобального weekly_schedule),
но фильтрует по конкретному master_id. Мастер редактировать не может —
этот роутер за IsAdminFilter.

Callback-namespace:
  master_sched_<id>                — открыть недельную сетку мастера
  msched_day_<id>_<weekday>        — детализация weekday
  msched_toggle_<id>_<weekday>     — toggle выходной
  msched_edit_start_<id>_<weekday> — FSM на редактирование часа начала
  msched_edit_end_<id>_<weekday>   — FSM на редактирование часа конца
"""
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from constants import WEEKDAYS_FULL_RU
from db import (
    get_master,
    get_master_schedule,
    update_master_weekday,
)
from db.connection import get_db
from keyboards.inline import (
    admin_cancel_keyboard,
    master_weekday_detail_keyboard,
    master_weekly_schedule_keyboard,
)
from states import AdminStates
from utils.admin import (
    IsAdminFilter,
    deny_access,
    is_admin_callback,
    is_admin_message,
)
from utils.callbacks import parse_callback
from utils.panel import edit_panel, edit_panel_with_callback

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(IsAdminFilter())
router.callback_query.filter(IsAdminFilter())


async def _count_master_schedule_conflicts(
    master_id: int,
    weekday: int,
    new_work_start: int,
    new_work_end: int,
) -> int:
    """Количество будущих scheduled записей мастера на указанный weekday,
    выходящих за новые часы работы. Паттерн из admin_settings.py."""
    # SQLite %w: Sun=0..Sat=6. Python Mon=0..Sun=6. Сдвиг +1 mod 7.
    sqlite_wd = str((weekday + 1) % 7)
    db = await get_db()
    cursor = await db.execute(
        """SELECT COUNT(*) FROM appointments
           WHERE master_id = ?
             AND status = 'scheduled'
             AND date >= date('now')
             AND strftime('%w', date) = ?
             AND (
                 CAST(substr(time, 1, 2) AS INTEGER) < ?
                 OR (CAST(substr(time, 1, 2) AS INTEGER) * 60
                     + CAST(substr(time, 4, 2) AS INTEGER)
                     + service_duration) > ? * 60
             )""",
        (master_id, sqlite_wd, new_work_start, new_work_end),
    )
    return (await cursor.fetchone())[0]


async def _show_master_weekly(callback: CallbackQuery, master_id: int) -> None:
    """Показать недельную сетку мастера в панели."""
    master = await get_master(master_id)
    if not master:
        await callback.answer("Мастер не найден.", show_alert=True)
        return
    schedule = await get_master_schedule(master_id)
    text = f"📆 <b>Расписание: {master['name']}</b>\n\nВыбери день для редактирования:"
    await edit_panel_with_callback(
        callback, text,
        master_weekly_schedule_keyboard(master_id, schedule),
        parse_mode="HTML",
    )


# ─── Открыть расписание мастера ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("master_sched_"))
async def cb_master_sched(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "master_sched", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    master_id = int(parts[0])
    await _show_master_weekly(callback, master_id)
    await callback.answer()


# ─── Детализация weekday ─────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("msched_day_"))
async def cb_msched_day(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "msched_day", 2)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    master_id, weekday = int(parts[0]), int(parts[1])

    schedule = await get_master_schedule(master_id)
    row = schedule.get(weekday) or {}
    is_day_off = row.get("work_start") is None
    day_name = WEEKDAYS_FULL_RU[weekday]

    if is_day_off:
        text = f"📅 {day_name} — выходной"
    else:
        text = f"📅 {day_name}  {row['work_start']:02d}:00 – {row['work_end']:02d}:00"

    await edit_panel_with_callback(
        callback, text,
        master_weekday_detail_keyboard(master_id, weekday, is_day_off),
    )
    await callback.answer()


# ─── Toggle выходной ─────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("msched_toggle_"))
async def cb_msched_toggle(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "msched_toggle", 2)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    master_id, weekday = int(parts[0]), int(parts[1])

    schedule = await get_master_schedule(master_id)
    row = schedule.get(weekday) or {}
    is_day_off = row.get("work_start") is None

    if is_day_off:
        # Возвращаем в рабочий день со стандартными часами 9-19.
        await update_master_weekday(master_id, weekday, 9, 19)
    else:
        await update_master_weekday(master_id, weekday, None, None)

    await _show_master_weekly(callback, master_id)
    await callback.answer()


# ─── Редактирование часа начала ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("msched_edit_start_"))
async def cb_msched_edit_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "msched_edit_start", 2)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    master_id, weekday = int(parts[0]), int(parts[1])
    await state.update_data(msched_master_id=master_id, msched_weekday=weekday)
    await edit_panel_with_callback(
        callback,
        "🕐 Введите час начала работы (0–22):",
        admin_cancel_keyboard(),
    )
    await state.set_state(AdminStates.master_schedule_edit_start)
    await callback.answer()


@router.message(AdminStates.master_schedule_edit_start)
async def msg_msched_edit_start(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass
    try:
        value = int(message.text.strip())
        if not (0 <= value <= 22):
            raise ValueError
    except (ValueError, AttributeError):
        await edit_panel(
            message.bot, message.chat.id,
            "⚠️ Введите целое число от 0 до 22:",
            admin_cancel_keyboard(),
        )
        return

    data = await state.get_data()
    master_id = data["msched_master_id"]
    weekday = data["msched_weekday"]

    schedule = await get_master_schedule(master_id)
    row = schedule.get(weekday) or {}
    work_end = row.get("work_end") or 19

    if value >= work_end:
        await edit_panel(
            message.bot, message.chat.id,
            f"⚠️ Начало должно быть меньше конца ({work_end:02d}:00):",
            admin_cancel_keyboard(),
        )
        return

    conflicts = await _count_master_schedule_conflicts(master_id, weekday, value, work_end)
    await update_master_weekday(master_id, weekday, value, work_end)
    await state.clear()

    master = await get_master(master_id)
    schedule = await get_master_schedule(master_id)
    text = f"📆 <b>Расписание: {master['name']}</b>\n\nВыбери день для редактирования:"
    parse_mode = "HTML"
    if conflicts > 0:
        text = (
            f"⚠️ <b>Внимание:</b> есть {conflicts} запись/записей вне новых часов работы. "
            "Проверьте «Все записи» — возможно, их нужно перенести.\n\n"
            + text
        )

    await edit_panel(
        message.bot, message.chat.id, text,
        master_weekly_schedule_keyboard(master_id, schedule),
        parse_mode=parse_mode,
    )


# ─── Редактирование часа конца ───────────────────────────────────────────────

@router.callback_query(F.data.startswith("msched_edit_end_"))
async def cb_msched_edit_end(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "msched_edit_end", 2)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    master_id, weekday = int(parts[0]), int(parts[1])
    await state.update_data(msched_master_id=master_id, msched_weekday=weekday)
    await edit_panel_with_callback(
        callback,
        "🕕 Введите час конца работы (1–23):",
        admin_cancel_keyboard(),
    )
    await state.set_state(AdminStates.master_schedule_edit_end)
    await callback.answer()


@router.message(AdminStates.master_schedule_edit_end)
async def msg_msched_edit_end(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass
    try:
        value = int(message.text.strip())
        if not (1 <= value <= 23):
            raise ValueError
    except (ValueError, AttributeError):
        await edit_panel(
            message.bot, message.chat.id,
            "⚠️ Введите целое число от 1 до 23:",
            admin_cancel_keyboard(),
        )
        return

    data = await state.get_data()
    master_id = data["msched_master_id"]
    weekday = data["msched_weekday"]

    schedule = await get_master_schedule(master_id)
    row = schedule.get(weekday) or {}
    work_start = row.get("work_start") or 9

    if value <= work_start:
        await edit_panel(
            message.bot, message.chat.id,
            f"⚠️ Конец должен быть больше начала ({work_start:02d}:00):",
            admin_cancel_keyboard(),
        )
        return

    conflicts = await _count_master_schedule_conflicts(master_id, weekday, work_start, value)
    await update_master_weekday(master_id, weekday, work_start, value)
    await state.clear()

    master = await get_master(master_id)
    schedule = await get_master_schedule(master_id)
    text = f"📆 <b>Расписание: {master['name']}</b>\n\nВыбери день для редактирования:"
    parse_mode = "HTML"
    if conflicts > 0:
        text = (
            f"⚠️ <b>Внимание:</b> есть {conflicts} запись/записей вне новых часов работы. "
            "Проверьте «Все записи» — возможно, их нужно перенести.\n\n"
            + text
        )

    await edit_panel(
        message.bot, message.chat.id, text,
        master_weekly_schedule_keyboard(master_id, schedule),
        parse_mode=parse_mode,
    )
