import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from constants import WEEKDAYS_FULL_RU
from states import AdminStates
from db import get_all_settings, set_setting, get_weekly_schedule, update_weekday_schedule
from db.connection import get_db
from keyboards.inline import (
    settings_keyboard, admin_cancel_keyboard,
    weekly_schedule_keyboard, weekday_detail_keyboard,
)
from utils.admin import is_admin_callback, is_admin_message, deny_access, IsAdminFilter
from utils.callbacks import parse_callback
from utils.panel import edit_panel, edit_panel_with_callback

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(IsAdminFilter())
router.callback_query.filter(IsAdminFilter())

VALID_SLOT_STEPS = {15, 20, 30, 60}


def _sqlite_weekday(python_weekday: int) -> str:
    # Python Mon=0..Sun=6, SQLite %w: Sun=0..Sat=6
    return str((python_weekday + 1) % 7)


async def _count_schedule_conflicts(weekday: int, new_work_start: int, new_work_end: int) -> int:
    """Количество будущих scheduled записей на указанный weekday, выходящих за новые рабочие часы."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT COUNT(*) FROM appointments
           WHERE status = 'scheduled'
             AND date >= date('now')
             AND strftime('%w', date) = ?
             AND (
                 CAST(substr(time, 1, 2) AS INTEGER) < ?
                 OR (CAST(substr(time, 1, 2) AS INTEGER) * 60
                     + CAST(substr(time, 4, 2) AS INTEGER)
                     + service_duration) > ? * 60
             )""",
        (_sqlite_weekday(weekday), new_work_start, new_work_end),
    )
    return (await cursor.fetchone())[0]


async def _show_settings(callback: CallbackQuery) -> None:
    settings = await get_all_settings()
    await edit_panel_with_callback(callback, "⚙️ Настройки графика работы:", settings_keyboard(settings))


async def _show_weekly(callback: CallbackQuery) -> None:
    schedule = await get_weekly_schedule()
    await edit_panel_with_callback(callback, "📅 График работы по дням:", weekly_schedule_keyboard(schedule))


# ─── НАСТРОЙКИ (главный экран) ────────────────────────────────────────────────

@router.callback_query(F.data == "admin_settings")
async def cb_admin_settings(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    await _show_settings(callback)
    await callback.answer()


# ─── ШАГ СЛОТОВ ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "settings_edit_step")
async def cb_settings_edit_step(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    await edit_panel_with_callback(
        callback,
        f"⏱ Введите шаг слотов в минутах.\nДопустимые значения: {', '.join(str(s) for s in sorted(VALID_SLOT_STEPS))}",
        admin_cancel_keyboard(),
    )
    await state.set_state(AdminStates.settings_edit_slot_step)
    await callback.answer()


@router.message(AdminStates.settings_edit_slot_step)
async def msg_settings_slot_step(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass
    try:
        value = int(message.text.strip())
        if value not in VALID_SLOT_STEPS:
            raise ValueError
    except (ValueError, AttributeError):
        await edit_panel(
            message.bot, message.chat.id,
            f"⚠️ Допустимые значения: {', '.join(str(s) for s in sorted(VALID_SLOT_STEPS))}",
            admin_cancel_keyboard(),
        )
        return

    await set_setting("slot_step", str(value))
    await state.clear()
    settings = await get_all_settings()
    await edit_panel(message.bot, message.chat.id, "⚙️ Настройки графика работы:", settings_keyboard(settings))


# ─── ЕЖЕНЕДЕЛЬНОЕ РАСПИСАНИЕ ─────────────────────────────────────────────────

@router.callback_query(F.data == "sched_weekly")
async def cb_sched_weekly(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    await _show_weekly(callback)
    await callback.answer()


@router.callback_query(F.data.startswith("sched_day_"))
async def cb_sched_day(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return

    parts = parse_callback(callback.data, "sched_day", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    weekday = int(parts[0])
    schedule = await get_weekly_schedule()
    row = schedule.get(weekday, {})
    is_day_off = row.get("work_start") is None
    day_name = WEEKDAYS_FULL_RU[weekday]

    if is_day_off:
        text = f"📅 {day_name} — выходной"
    else:
        text = f"📅 {day_name}  {row['work_start']:02d}:00 – {row['work_end']:02d}:00"

    await edit_panel_with_callback(callback, text, weekday_detail_keyboard(weekday, is_day_off))
    await callback.answer()


@router.callback_query(F.data.startswith("sched_toggle_"))
async def cb_sched_toggle(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return

    parts = parse_callback(callback.data, "sched_toggle", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    weekday = int(parts[0])
    schedule = await get_weekly_schedule()
    row = schedule.get(weekday, {})
    is_day_off = row.get("work_start") is None

    if is_day_off:
        await update_weekday_schedule(weekday, 9, 19)
    else:
        await update_weekday_schedule(weekday, None, None)

    await _show_weekly(callback)
    await callback.answer()


@router.callback_query(F.data.startswith("sched_edit_start_"))
async def cb_sched_edit_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return

    parts = parse_callback(callback.data, "sched_edit_start", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    weekday = int(parts[0])
    await state.update_data(sched_weekday=weekday)
    await edit_panel_with_callback(callback, "🕐 Введите час начала работы (0–22):", admin_cancel_keyboard())
    await state.set_state(AdminStates.schedule_edit_start)
    await callback.answer()


@router.message(AdminStates.schedule_edit_start)
async def msg_sched_edit_start(message: Message, state: FSMContext):
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
        await edit_panel(message.bot, message.chat.id, "⚠️ Введите целое число от 0 до 22:", admin_cancel_keyboard())
        return

    data = await state.get_data()
    weekday = data["sched_weekday"]
    schedule = await get_weekly_schedule()
    work_end = (schedule.get(weekday) or {}).get("work_end") or 19

    if value >= work_end:
        await edit_panel(
            message.bot, message.chat.id,
            f"⚠️ Начало должно быть меньше конца ({work_end:02d}:00):",
            admin_cancel_keyboard(),
        )
        return

    conflicts = await _count_schedule_conflicts(weekday, value, work_end)

    await update_weekday_schedule(weekday, value, work_end)
    await state.clear()

    msg_text = "📅 График работы по дням:"
    parse_mode = None
    if conflicts > 0:
        msg_text = (
            f"⚠️ <b>Внимание:</b> есть {conflicts} запись/записей вне новых часов работы. "
            "Проверьте «Все записи» — возможно, их нужно перенести.\n\n"
            + msg_text
        )
        parse_mode = "HTML"

    schedule = await get_weekly_schedule()
    await edit_panel(
        message.bot, message.chat.id, msg_text,
        weekly_schedule_keyboard(schedule),
        parse_mode=parse_mode,
    )


@router.callback_query(F.data.startswith("sched_edit_end_"))
async def cb_sched_edit_end(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return

    parts = parse_callback(callback.data, "sched_edit_end", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    weekday = int(parts[0])
    await state.update_data(sched_weekday=weekday)
    await edit_panel_with_callback(callback, "🕕 Введите час конца работы (1–23):", admin_cancel_keyboard())
    await state.set_state(AdminStates.schedule_edit_end)
    await callback.answer()


@router.message(AdminStates.schedule_edit_end)
async def msg_sched_edit_end(message: Message, state: FSMContext):
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
        await edit_panel(message.bot, message.chat.id, "⚠️ Введите целое число от 1 до 23:", admin_cancel_keyboard())
        return

    data = await state.get_data()
    weekday = data["sched_weekday"]
    schedule = await get_weekly_schedule()
    work_start = (schedule.get(weekday) or {}).get("work_start") or 9

    if value <= work_start:
        await edit_panel(
            message.bot, message.chat.id,
            f"⚠️ Конец должен быть больше начала ({work_start:02d}:00):",
            admin_cancel_keyboard(),
        )
        return

    conflicts = await _count_schedule_conflicts(weekday, work_start, value)

    await update_weekday_schedule(weekday, work_start, value)
    await state.clear()

    msg_text = "📅 График работы по дням:"
    parse_mode = None
    if conflicts > 0:
        msg_text = (
            f"⚠️ <b>Внимание:</b> есть {conflicts} запись/записей вне новых часов работы. "
            "Проверьте «Все записи» — возможно, их нужно перенести.\n\n"
            + msg_text
        )
        parse_mode = "HTML"

    schedule = await get_weekly_schedule()
    await edit_panel(
        message.bot, message.chat.id, msg_text,
        weekly_schedule_keyboard(schedule),
        parse_mode=parse_mode,
    )
