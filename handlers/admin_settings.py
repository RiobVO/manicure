import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.fsm.context import FSMContext

from constants import WEEKDAYS_FULL_RU
from states import AdminStates
from db import (
    get_all_settings, set_setting,
    get_weekly_schedule, update_weekday_schedule,
    get_categories_config,
)
from db.connection import get_db
from keyboards.inline import (
    settings_keyboard, admin_cancel_keyboard,
    weekly_schedule_keyboard, weekday_detail_keyboard,
    categories_menu_keyboard,
)
from utils.admin import is_admin_callback, is_admin_message, deny_access, IsAdminFilter
from utils.callbacks import parse_callback
from utils.panel import edit_panel, edit_panel_with_callback
from utils.ui import h

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
# Допустимых значений всего четыре — даём четыре кнопки вместо текстового
# ввода. Текущее значение помечаем «✓», чтобы было видно с первого взгляда.

def _slot_step_keyboard(current: int) -> InlineKeyboardMarkup:
    row: list[InlineKeyboardButton] = []
    for value in sorted(VALID_SLOT_STEPS):
        label = f"{value} мин ✓" if value == current else f"{value} мин"
        row.append(InlineKeyboardButton(
            text=label,
            callback_data=f"slot_step_set_{value}",
        ))
    return InlineKeyboardMarkup(inline_keyboard=[
        row,
        [InlineKeyboardButton(text="↩️ Назад", callback_data="admin_settings")],
    ])


@router.callback_query(F.data == "settings_edit_step")
async def cb_settings_edit_step(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    await state.clear()
    settings = await get_all_settings()
    try:
        current = int(settings.get("slot_step", 30))
    except (TypeError, ValueError):
        current = 30
    await edit_panel_with_callback(
        callback,
        (
            "⏱ <b>Шаг слотов</b>\n\n"
            f"Сейчас: <b>{current} мин</b>\n\n"
            "Сколько минут между записями? Чем меньше шаг — тем точнее "
            "клиент подберёт удобное время, но больше «дробных» окон в дне."
        ),
        _slot_step_keyboard(current),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("slot_step_set_"))
async def cb_slot_step_set(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "slot_step_set", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    try:
        value = int(parts[0])
    except ValueError:
        await callback.answer()
        return
    # Whitelist: callback извне, защищаемся от подделанной строки.
    if value not in VALID_SLOT_STEPS:
        logger.warning("cb_slot_step_set: bad value=%r", value)
        await callback.answer()
        return
    await set_setting("slot_step", str(value))
    await callback.answer(f"✅ Шаг: {value} мин")
    settings = await get_all_settings()
    await edit_panel_with_callback(
        callback, "⚙️ Настройки графика работы:", settings_keyboard(settings),
    )


# ─── КОНТАКТ ДЛЯ КЛИЕНТОВ ────────────────────────────────────────────────────
# Показывается клиенту, например, в сообщении об отмене оплаченной записи.
# Пусто → бот пишет нейтральное «свяжись с салоном», чтобы не дать ложных
# обещаний (например, «пиши сюда», когда реального приёма нет).
_CONTACT_MAX_LEN = 64
_SALON_NAME_MAX_LEN = 40  # помещается в одну строку на QR-плакате при 22pt


@router.callback_query(F.data == "settings_edit_contact")
async def cb_settings_edit_contact(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    current = (await get_all_settings()).get("salon_contact", "") or "не задан"
    await edit_panel_with_callback(
        callback,
        (
            "📞 <b>Контакт для клиентов</b>\n\n"
            f"Сейчас: <code>{current}</code>\n\n"
            "Отправь новое значение одним сообщением — это может быть\n"
            "• Telegram-handle: <code>@your_salon</code>\n"
            "• Телефон: <code>+998 90 123 45 67</code>\n"
            "• Короткая фраза: <code>напиши в директ @your_salon</code>\n\n"
            "Чтобы <b>очистить</b>, пришли одно слово <code>-</code> или <code>нет</code>.\n"
            f"Макс. длина — {_CONTACT_MAX_LEN} символов."
        ),
        admin_cancel_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(AdminStates.settings_edit_contact)
    await callback.answer()


@router.message(AdminStates.settings_edit_contact)
async def msg_settings_contact(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass

    text = (message.text or "").strip()
    # Команда очистки.
    if text.lower() in {"-", "нет", "no", "off", "clear"}:
        text = ""
    elif len(text) > _CONTACT_MAX_LEN:
        await edit_panel(
            message.bot, message.chat.id,
            f"⚠️ Слишком длинно (макс. {_CONTACT_MAX_LEN} символов). Пришли короче:",
            admin_cancel_keyboard(),
        )
        return

    await set_setting("salon_contact", text)
    await state.clear()
    settings = await get_all_settings()
    await edit_panel(
        message.bot, message.chat.id,
        "⚙️ Настройки графика работы:",
        settings_keyboard(settings),
    )


# ─── НАЗВАНИЕ САЛОНА (для QR-плакатов) ──────────────────────────────────────

@router.callback_query(F.data == "settings_edit_name")
async def cb_settings_edit_name(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    current = (await get_all_settings()).get("salon_name", "") or "не задано"
    await edit_panel_with_callback(
        callback,
        (
            "🏷 <b>Название салона</b>\n\n"
            f"Сейчас: <code>{current}</code>\n\n"
            "Используется как мелкая строка сверху на QR-плакатах "
            "(«📈 Откуда клиенты» → «📱 QR для печати»).\n\n"
            "Пришли новое значение одним сообщением. Пример:\n"
            "<code>Nail Studio Demo</code>\n\n"
            "Чтобы <b>очистить</b>, пришли <code>-</code> или <code>нет</code>.\n"
            f"Макс. длина — {_SALON_NAME_MAX_LEN} символов."
        ),
        admin_cancel_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(AdminStates.settings_edit_name)
    await callback.answer()


@router.message(AdminStates.settings_edit_name)
async def msg_settings_name(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass

    text = (message.text or "").strip()
    if text.lower() in {"-", "нет", "no", "off", "clear"}:
        text = ""
    elif len(text) > _SALON_NAME_MAX_LEN:
        await edit_panel(
            message.bot, message.chat.id,
            f"⚠️ Слишком длинно (макс. {_SALON_NAME_MAX_LEN} символов). Пришли короче:",
            admin_cancel_keyboard(),
        )
        return

    await set_setting("salon_name", text)
    await state.clear()
    settings = await get_all_settings()
    await edit_panel(
        message.bot, message.chat.id,
        "⚙️ Настройки графика работы:",
        settings_keyboard(settings),
    )


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


# ─── КАТЕГОРИИ УСЛУГ (универсальный режим) ──────────────────────────────────
# settings.use_categories вкл/выкл + подписи cat_a_label/cat_b_label.
# Под капотом БД всегда хранит services.category в enum {'hands','feet'} —
# мы трогаем только UI-слой. Тесты не страдают.
_CAT_LABEL_MAX_LEN = 30  # с запасом помещается в inline-кнопку


def _categories_menu_text(cfg: dict) -> str:
    """HTML-текст экрана «🏷 Категории услуг».
    Подписи категорий обёрнуты h() — владелец может ввести угловые скобки/амперсанды
    в названии («<premium>», «Brows&Lashes»), без эскейпа parse_mode=HTML упадёт."""
    if cfg["use_categories"]:
        return (
            "🏷 <b>Категории услуг</b>\n\n"
            "Сейчас режим: <b>две категории</b>\n"
            f"• Категория А: <b>{h(cfg['label_a'])}</b>\n"
            f"• Категория Б: <b>{h(cfg['label_b'])}</b>\n\n"
            "Клиент сначала выбирает категорию, потом услугу из этой категории.\n\n"
            "<i>Если у тебя салон одного типа (только депиляция, только массаж) — "
            "переключи на «плоский список», клиент будет сразу видеть все услуги.</i>"
        )
    return (
        "🏷 <b>Категории услуг</b>\n\n"
        "Сейчас режим: <b>плоский список</b>\n\n"
        "Клиент сразу видит все услуги без шага выбора категории. "
        "Подходит для салонов одного типа.\n\n"
        "<i>Если хочешь группировку (например «Стрижки» / «Окрашивание») — "
        "переключи режим, потом задай подписи категорий.</i>"
    )


async def _show_categories_menu(callback: CallbackQuery) -> None:
    cfg = await get_categories_config()
    await edit_panel_with_callback(
        callback,
        _categories_menu_text(cfg),
        categories_menu_keyboard(cfg["use_categories"]),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "settings_categories_menu")
async def cb_settings_categories_menu(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    await state.clear()
    await _show_categories_menu(callback)
    await callback.answer()


@router.callback_query(F.data == "settings_categories_toggle")
async def cb_settings_categories_toggle(callback: CallbackQuery, state: FSMContext):
    """Переключить use_categories. Остаёмся на том же экране — владелец
    видит как изменилось состояние."""
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    await state.clear()
    cfg = await get_categories_config()
    new_value = "0" if cfg["use_categories"] else "1"
    await set_setting("use_categories", new_value)
    new_state_label = "две категории" if new_value == "1" else "плоский список"
    try:
        await callback.answer(f"✅ Режим: {new_state_label}", show_alert=False)
    except Exception:
        pass
    await _show_categories_menu(callback)


# ─── Редактирование подписей А / Б ──────────────────────────────────────────

def _category_edit_prompt(which: str, current: str) -> str:
    return (
        f"✏ <b>Подпись категории {which}</b>\n\n"
        f"Сейчас: <code>{h(current)}</code>\n\n"
        "Пришли новую подпись одним сообщением. Можно с эмодзи в начале:\n"
        "<code>✂️ Стрижки</code>\n"
        "<code>🦷 Депиляция тела</code>\n\n"
        f"Макс. длина — {_CAT_LABEL_MAX_LEN} символов."
    )


@router.callback_query(F.data == "settings_edit_cat_a")
async def cb_settings_edit_cat_a(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    cfg = await get_categories_config()
    await edit_panel_with_callback(
        callback,
        _category_edit_prompt("А", cfg["label_a"]),
        admin_cancel_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(AdminStates.settings_edit_cat_a_label)
    await callback.answer()


@router.callback_query(F.data == "settings_edit_cat_b")
async def cb_settings_edit_cat_b(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    cfg = await get_categories_config()
    await edit_panel_with_callback(
        callback,
        _category_edit_prompt("Б", cfg["label_b"]),
        admin_cancel_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(AdminStates.settings_edit_cat_b_label)
    await callback.answer()


async def _save_cat_label(
    message: Message, state: FSMContext, key: str,
) -> None:
    """Общая логика сохранения для cat_a/cat_b — отличается только key."""
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass
    text = (message.text or "").strip()
    if not text:
        await edit_panel(
            message.bot, message.chat.id,
            "⚠️ Пустая подпись не подходит. Пришли непустой текст:",
            admin_cancel_keyboard(),
        )
        return
    if len(text) > _CAT_LABEL_MAX_LEN:
        await edit_panel(
            message.bot, message.chat.id,
            f"⚠️ Слишком длинно (макс. {_CAT_LABEL_MAX_LEN} символов). Пришли короче:",
            admin_cancel_keyboard(),
        )
        return
    await set_setting(key, text)
    await state.clear()
    cfg = await get_categories_config()
    await edit_panel(
        message.bot, message.chat.id,
        _categories_menu_text(cfg),
        categories_menu_keyboard(cfg["use_categories"]),
        parse_mode="HTML",
    )


@router.message(AdminStates.settings_edit_cat_a_label)
async def msg_cat_a_label(message: Message, state: FSMContext):
    await _save_cat_label(message, state, "cat_a_label")


@router.message(AdminStates.settings_edit_cat_b_label)
async def msg_cat_b_label(message: Message, state: FSMContext):
    await _save_cat_label(message, state, "cat_b_label")
