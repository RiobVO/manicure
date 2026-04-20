"""
Кабинет мастера: read-only pull-интерфейс для мастера в том же боте.

Попадание сюда означает, что user_id привязан к активному мастеру.
Role-routing происходит в handlers/client.py::cmd_start (elif is_master),
entry-функция ниже вызывается оттуда.

Никакого FSM. Три reply-кнопки — 'Сегодня', 'Мои записи', 'Расписание'.
Все три пишут через edit_panel в единое сообщение-панель (как админка).
"""
import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from constants import MONTHS_RU, WEEKDAYS_FULL_RU, WEEKDAYS_SHORT_RU
from config import ADMIN_IDS
from db import (
    add_master_day_off,
    count_master_scheduled_on_date,
    delete_master_day_off,
    get_appointment_by_id,
    get_future_master_day_offs,
    get_master,
    get_master_appointments_today,
    get_master_appointments_upcoming,
    get_master_by_user_id,
    get_master_schedule,
    log_admin_action,
    reschedule_appointment,
    update_appointment_status,
)
from keyboards.inline import (
    master_appt_actions_keyboard,
    master_back_to_schedule_keyboard,
    master_day_off_dates_keyboard,
    master_day_off_remove_keyboard,
    master_reply_keyboard,
    master_rs_dates_keyboard,
    master_rs_times_keyboard,
    master_schedule_menu_keyboard,
    master_today_list_keyboard,
    master_upcoming_list_keyboard,
)
from services.booking import compute_free_slots
from states import MasterStates
from utils.admin import IsMasterFilter
from utils.callbacks import parse_callback
from utils.notifications import broadcast_to_admins, notify_client
from utils.panel import (
    clear_panel_msg_id,
    get_panel_lock,
    get_panel_msg_id,
    set_panel_msg_id,
    set_reply_kb,
)
from utils.timezone import now_local
from utils.ui import h

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(IsMasterFilter())
router.callback_query.filter(IsMasterFilter())

_STATUS_ICON = {"scheduled": "🕐", "completed": "✅", "no_show": "🚫"}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _date_human(date_str: str) -> str:
    """YYYY-MM-DD → '20 апреля, пн'."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.day} {MONTHS_RU[dt.month - 1]}, {WEEKDAYS_SHORT_RU[dt.weekday()]}"
    except ValueError:
        return date_str


def _duration_str(minutes: int) -> str:
    """60 → '1ч', 90 → '1ч 30м', 45 → '45м'."""
    if minutes < 60:
        return f"{minutes}м"
    h, m = divmod(minutes, 60)
    return f"{h}ч" if m == 0 else f"{h}ч {m}м"


async def _nav(
    message: Message,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
) -> None:
    """
    Удалить сообщение-тап (текст кнопки), отредактировать панель мастера или
    создать новую. Паттерн скопирован из handlers/admin.py::_nav.
    markup опционален: v.3 Phase 1 добавила inline-кнопки в «📆 Моё расписание»,
    но другие разделы (Сегодня/Мои записи) остаются read-only без markup.
    """
    chat_id = message.chat.id
    lock = get_panel_lock(chat_id)
    async with lock:
        try:
            await message.delete()
        except Exception:
            pass  # уже удалено или нет прав — не блокируем навигацию

        nav_id = get_panel_msg_id(chat_id)
        if nav_id:
            try:
                await message.bot.edit_message_text(
                    text, chat_id=chat_id, message_id=nav_id,
                    reply_markup=markup,
                    parse_mode=parse_mode,
                )
                return
            except TelegramBadRequest:
                try:
                    await message.bot.delete_message(chat_id, nav_id)
                except Exception:
                    pass
                clear_panel_msg_id(chat_id)

        sent = await message.bot.send_message(
            chat_id, text, reply_markup=markup, parse_mode=parse_mode,
        )
        set_panel_msg_id(chat_id, sent.message_id)


# ─── Entry (вызывается из client.py::cmd_start) ──────────────────────────────

async def show_master_cabinet_entry(message: Message, state: FSMContext) -> None:
    """
    Встречает мастера после /start: ставит reply-клавиатуру и показывает
    приветствие с именем. Вызывается из client.py::cmd_start при is_master.
    """
    await state.clear()
    master = await get_master_by_user_id(message.from_user.id)
    if master is None:
        # Гонка: между IsMasterFilter и этим вызовом мастер был деактивирован.
        # Тихо выходим — пусть следующий /start попадёт в клиентский флоу.
        return

    # Удаляем /start-сообщение. except Exception — симметрично _nav() и
    # handlers/admin.py: ловим TelegramBadRequest + потерю прав/бан/race,
    # не блокируем вход в кабинет из-за мусорной ошибки удаления.
    try:
        await message.delete()
    except Exception:
        pass

    set_reply_kb(message.chat.id, master_reply_keyboard())
    await message.answer(
        f"👨\u200d🎨 <b>Кабинет мастера</b>\n"
        f"<i>{h(master['name'])}</i>\n\n"
        f"Выбери что посмотреть ↓",
        reply_markup=master_reply_keyboard(),
        parse_mode="HTML",
    )


# ─── Reply buttons ───────────────────────────────────────────────────────────

async def _render_today_payload(
    master_id: int,
) -> tuple[str, InlineKeyboardMarkup | None]:
    """Общий рендер «📋 Сегодня» — текст + клавиатура записей-кнопок.
    Вынесено из msg_today, чтобы после смены статуса (callback) можно
    было одной строкой перерисовать тот же экран."""
    date_str = now_local().strftime("%Y-%m-%d")
    appointments = await get_master_appointments_today(master_id, date_str)

    if not appointments:
        text = (
            f"📋 <b>Сегодня, {_date_human(date_str)}</b>\n\n"
            f"<i>Записей нет. Хорошего дня.</i>"
        )
        return text, None

    lines = [f"📋 <b>Сегодня, {_date_human(date_str)}</b>"]
    for a in appointments:
        icon = _STATUS_ICON.get(a["status"], "·")
        lines.append(
            f"\n{icon} <b>{a['time']}</b> — {h(a['name'])}\n"
            f"   💅 {h(a['service_name'])} ({_duration_str(a['service_duration'])})\n"
            f"   📞 {h(a['phone'])}"
        )
    lines.append("\n<i>Нажми на запись, чтобы отметить или перенести.</i>")
    return "\n".join(lines), master_today_list_keyboard(appointments)


async def _render_upcoming_payload(
    master_id: int,
) -> tuple[str, InlineKeyboardMarkup | None]:
    """Общий рендер «📅 Мои записи»."""
    today = now_local().strftime("%Y-%m-%d")
    appointments = await get_master_appointments_upcoming(master_id, today, limit=30)

    if not appointments:
        return (
            "📅 <b>Твои ближайшие записи</b>\n\n<i>Пока ничего запланировано.</i>",
            None,
        )

    lines = ["📅 <b>Твои ближайшие записи</b>"]
    current_date = None
    for a in appointments:
        if a["date"] != current_date:
            current_date = a["date"]
            lines.append(f"\n<b>—— {_date_human(current_date)} ——</b>")
        lines.append(
            f"🕐 <b>{a['time']}</b> — {h(a['name'])} · {h(a['service_name'])}"
        )
    if len(appointments) == 30:
        lines.append("\n<i>... показаны первые 30. Остальные — позже.</i>")
    lines.append("\n<i>Нажми на запись для действий.</i>")
    return "\n".join(lines), master_upcoming_list_keyboard(appointments)


@router.message(StateFilter("*"), F.text == "📋 Сегодня")
async def msg_today(message: Message, state: FSMContext) -> None:
    """Сегодняшние записи: scheduled + completed + no_show. Без cancelled.
    Каждая запись — inline-кнопка, открывает карточку с действиями."""
    await state.clear()
    master = await get_master_by_user_id(message.from_user.id)
    if master is None:
        return

    text, markup = await _render_today_payload(master["id"])
    await _nav(message, text, markup=markup, parse_mode="HTML")


@router.message(StateFilter("*"), F.text == "📅 Мои записи")
async def msg_upcoming(message: Message, state: FSMContext) -> None:
    """Ближайшие scheduled на сегодня и вперёд, до 30 штук, группировка по дате.
    Каждая запись — inline-кнопка."""
    await state.clear()
    master = await get_master_by_user_id(message.from_user.id)
    if master is None:
        return

    text, markup = await _render_upcoming_payload(master["id"])
    await _nav(message, text, markup=markup, parse_mode="HTML")


async def _render_schedule_payload(
    master_id: int,
) -> tuple[str, InlineKeyboardMarkup]:
    """Общий рендер «📆 Моё расписание»: текст с недельной сеткой + будущими
    отгулами + inline-меню действий. Используется из msg_schedule и из
    callbacks (mdo_back, после add/remove), чтобы не дублировать логику."""
    schedule = await get_master_schedule(master_id)
    day_offs = await get_future_master_day_offs(master_id)

    lines = ["📆 <b>Твоё расписание</b>\n"]
    for weekday in range(7):
        row = schedule.get(weekday)
        day_name = WEEKDAYS_FULL_RU[weekday]
        if row is None or row["work_start"] is None:
            lines.append(f"<b>{day_name}</b> — <i>выходной</i>")
        else:
            lines.append(
                f"<b>{day_name}</b>  <code>{row['work_start']:02d}:00 – {row['work_end']:02d}:00</code>"
            )

    if day_offs:
        lines.append("\n<b>Будущие отгулы:</b>")
        for d in day_offs:
            lines.append(f"· {_date_human(d['date'])}")

    lines.append("\n<i>Часы работы — через администратора.</i>")
    markup = master_schedule_menu_keyboard(has_day_offs=bool(day_offs))
    return "\n".join(lines), markup


@router.message(StateFilter("*"), F.text == "📆 Моё расписание")
async def msg_schedule(message: Message, state: FSMContext) -> None:
    """Недельная сетка из master_schedule + inline-меню отгулов."""
    await state.clear()
    master = await get_master_by_user_id(message.from_user.id)
    if master is None:
        return

    text, markup = await _render_schedule_payload(master["id"])
    await _nav(message, text, markup=markup, parse_mode="HTML")


# ─── Self-serve day-off: callbacks ───────────────────────────────────────────


async def _edit_to_schedule(callback: CallbackQuery, master_id: int) -> None:
    """Перерисовать сообщение в экран расписания. Используется после add/remove
    отгула и в «🔙 К расписанию»."""
    text, markup = await _render_schedule_payload(master_id)
    try:
        await callback.message.edit_text(
            text, reply_markup=markup, parse_mode="HTML",
        )
    except TelegramBadRequest:
        # Сообщение устарело / идентично — тихо игнорируем, callback.answer
        # вызовется в вызывающем коде.
        pass


@router.callback_query(F.data == "mdo_add")
async def cb_mdo_add(callback: CallbackQuery) -> None:
    """Открыть календарь выбора даты для постановки отгула."""
    try:
        await callback.message.edit_text(
            "🌙 Выбери день для отгула:",
            reply_markup=master_day_off_dates_keyboard(),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("mdo_pick_"))
async def cb_mdo_pick(callback: CallbackQuery) -> None:
    """Мастер выбрал дату для отгула. Проверяем:
    (1) не стоит ли уже отгул — идемпотентность;
    (2) нет ли scheduled записей — conflict guard.
    В обоих случаях — warning без мутации. Только при чистой проверке сохраняем
    + шлём push админам."""
    parts = parse_callback(callback.data, "mdo_pick", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    date_str = parts[0]

    master = await get_master_by_user_id(callback.from_user.id)
    if master is None:
        await callback.answer()
        return

    existing = await get_future_master_day_offs(master["id"])
    if any(d["date"] == date_str for d in existing):
        await callback.answer("На эту дату уже стоит отгул.", show_alert=True)
        return

    conflicts = await count_master_scheduled_on_date(master["id"], date_str)
    if conflicts > 0:
        word = "запись" if conflicts == 1 else "записей"
        try:
            await callback.message.edit_text(
                f"⚠️ На {_date_human(date_str)} у тебя {conflicts} {word}.\n\n"
                f"Сначала попроси администратора отменить или перенести их, "
                f"потом возвращайся — поставишь отгул.",
                reply_markup=master_back_to_schedule_keyboard(),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
        await callback.answer()
        return

    await add_master_day_off(master["id"], date_str)

    # Push админам — fire-and-forget, сбой не валит основной UX.
    try:
        await broadcast_to_admins(
            callback.bot,
            f"🌙 <b>[{h(master['name'])}]</b> поставил(а) отгул на "
            f"<b>{_date_human(date_str)}</b>.",
            log_context="master day-off added",
        )
    except Exception:
        logger.exception("Не удалось уведомить админов об отгуле мастера")

    await _edit_to_schedule(callback, master["id"])
    await callback.answer(f"Отгул на {_date_human(date_str)} поставлен.")


@router.callback_query(F.data == "mdo_remove_list")
async def cb_mdo_remove_list(callback: CallbackQuery) -> None:
    """Список будущих отгулов мастера для удаления."""
    master = await get_master_by_user_id(callback.from_user.id)
    if master is None:
        await callback.answer()
        return

    day_offs = await get_future_master_day_offs(master["id"])
    if not day_offs:
        # Race: между показом кнопки и кликом отгул мог исчезнуть.
        await callback.answer("Будущих отгулов нет.", show_alert=True)
        await _edit_to_schedule(callback, master["id"])
        return

    try:
        await callback.message.edit_text(
            "☀ Выбери отгул для отмены:",
            reply_markup=master_day_off_remove_keyboard(day_offs),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("mdo_del_"))
async def cb_mdo_del(callback: CallbackQuery) -> None:
    """Удаление конкретного отгула. delete_master_day_off сам проверяет, что
    строка принадлежит этому master_id — защита от подмены block_id через
    тухлый callback другого мастера."""
    parts = parse_callback(callback.data, "mdo_del", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    try:
        block_id = int(parts[0])
    except ValueError:
        await callback.answer()
        return

    master = await get_master_by_user_id(callback.from_user.id)
    if master is None:
        await callback.answer()
        return

    # Достанем дату ДО удаления, чтобы сказать в push админам что именно убрали.
    day_offs = await get_future_master_day_offs(master["id"])
    target = next((d for d in day_offs if d["id"] == block_id), None)

    removed = await delete_master_day_off(block_id, master["id"])
    if not removed:
        await callback.answer("Отгул не найден.", show_alert=True)
        await _edit_to_schedule(callback, master["id"])
        return

    if target is not None:
        try:
            await broadcast_to_admins(
                callback.bot,
                f"☀ <b>[{h(master['name'])}]</b> убрал(а) отгул на "
                f"<b>{_date_human(target['date'])}</b>.",
                log_context="master day-off removed",
            )
        except Exception:
            logger.exception("Не удалось уведомить админов об отмене отгула")

    await _edit_to_schedule(callback, master["id"])
    await callback.answer("Отгул убран.")


@router.callback_query(F.data == "mdo_back")
async def cb_mdo_back(callback: CallbackQuery) -> None:
    """«🔙 К расписанию» — вернуться к экрану с недельной сеткой и меню."""
    master = await get_master_by_user_id(callback.from_user.id)
    if master is None:
        await callback.answer()
        return
    await _edit_to_schedule(callback, master["id"])
    await callback.answer()


# ─── Self-serve appointment actions (v.3 Phase 2) ────────────────────────────
# Мастер жмёт на запись из «Сегодня»/«Мои записи» → карточка → действия.
# Guard: мастер управляет ТОЛЬКО своими записями. Проверка appt.master_id
# против master.id (по user_id) в каждом callback — never trust callback_data.


_STATUS_WORD = {
    "completed": "✅ Выполнено",
    "no_show":   "🚫 Не пришёл",
    "cancelled": "❌ Отменено",
    "scheduled": "🕐 Ожидает",
}


async def _load_master_appt(
    callback: CallbackQuery, appt_id: int,
) -> tuple[dict, dict] | None:
    """Прогрузить мастера (по user_id) и запись (по id) с проверкой владения.
    Возвращает (master, appt) или None если что-то не сошлось.
    В случае None — сам отвечает на callback, вызывающему остаётся return."""
    master = await get_master_by_user_id(callback.from_user.id)
    if master is None:
        await callback.answer()
        return None
    appt = await get_appointment_by_id(appt_id)
    if appt is None:
        await callback.answer("Запись не найдена.", show_alert=True)
        return None
    if appt.get("master_id") != master["id"]:
        # Не кричим пользователю «чужая запись» — просто не даём. Скорее всего
        # тухлый callback после того, как админ переназначил мастера.
        await callback.answer("Запись недоступна.", show_alert=True)
        return None
    return master, appt


def _appt_card_text(appt: dict) -> str:
    """Текст карточки записи — переиспользуется в открытии/после смены статуса."""
    status_label = _STATUS_WORD.get(appt["status"], appt["status"])
    return (
        f"📋 <b>Запись #{appt['id']}</b>\n\n"
        f"🕐 <b>{appt['time']}</b> · {_date_human(appt['date'])}\n"
        f"👤 {h(appt['name'])}\n"
        f"📞 {h(appt['phone'])}\n"
        f"💅 {h(appt['service_name'])} ({_duration_str(appt['service_duration'])})\n"
        f"📌 {status_label}"
    )


@router.callback_query(F.data == "mappt_back")
async def cb_mappt_back(callback: CallbackQuery, state: FSMContext) -> None:
    """«🔙 К записям» из карточки. Возвращаемся к «📋 Сегодня» —
    самый частый кейс (утренний ритм), а не к «📅 Мои записи»."""
    await state.clear()
    master = await get_master_by_user_id(callback.from_user.id)
    if master is None:
        await callback.answer()
        return
    text, markup = await _render_today_payload(master["id"])
    try:
        await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(
    F.data.startswith("mappt_")
    & ~F.data.startswith("mappt_status_")
    & ~F.data.startswith("mappt_rs_")
    & ~F.data.startswith("mappt_rsd_")
    & ~F.data.startswith("mappt_rst_")
    & (F.data != "mappt_back")
)
async def cb_mappt_card(callback: CallbackQuery, state: FSMContext) -> None:
    """Открытие карточки записи. Callback `mappt_<id>`."""
    await state.clear()
    parts = parse_callback(callback.data, "mappt", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    try:
        appt_id = int(parts[0])
    except ValueError:
        await callback.answer()
        return

    loaded = await _load_master_appt(callback, appt_id)
    if loaded is None:
        return
    _, appt = loaded

    try:
        await callback.message.edit_text(
            _appt_card_text(appt),
            reply_markup=master_appt_actions_keyboard(appt_id, appt["status"]),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("mappt_status_"))
async def cb_mappt_status(callback: CallbackQuery) -> None:
    """Смена статуса записи мастером. Callback `mappt_status_<id>_<status>`.
    Для cancelled — дополнительный push клиенту.
    Все статусы — push админам и admin_logs.log_admin_action (аудит)."""
    parts = parse_callback(callback.data, "mappt_status", 2)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    try:
        appt_id = int(parts[0])
    except ValueError:
        await callback.answer()
        return
    status = parts[1]
    if status not in ("completed", "no_show", "cancelled"):
        await callback.answer()
        return

    loaded = await _load_master_appt(callback, appt_id)
    if loaded is None:
        return
    master, appt = loaded

    await update_appointment_status(appt_id, status)

    await log_admin_action(
        admin_id=callback.from_user.id,
        action=f"master_status_{status}",
        target_type="appointment",
        target_id=appt_id,
        details=(
            f"[{master['name']}] {appt['name']} — {appt['service_name']} "
            f"({appt['date']} {appt['time']})"
        ),
    )

    # Push клиенту — только на отмену мастером. completed / no_show клиенту
    # не уведомляем: completed — сам знает что был, no_show — не пришёл, не нужен spam.
    if status == "cancelled":
        try:
            await notify_client(
                callback.bot, appt["user_id"], "cancelled_by_master",
                {
                    "master_name": master["name"].title(),
                    "date": appt["date"],
                    "time": appt["time"],
                    "service_name": appt["service_name"],
                },
            )
        except Exception:
            logger.exception("notify_client(cancelled_by_master) упал")

    # Push админам. Если мастер сам = админ (есть в ADMIN_IDS), шум не нужен.
    if callback.from_user.id not in ADMIN_IDS:
        label = _STATUS_WORD.get(status, status)
        try:
            await broadcast_to_admins(
                callback.bot,
                f"{label[:2]} <b>[{h(master['name'])}]</b> обновил(а) запись "
                f"{h(appt['name'])} на {appt['date']} {appt['time']}: "
                f"<b>{label}</b>.",
                log_context="master status change",
            )
        except Exception:
            logger.exception("broadcast_to_admins упал (статус от мастера)")

    # Перерисовать карточку с новым статусом.
    fresh = await get_appointment_by_id(appt_id)
    if fresh is None:
        await callback.answer()
        return
    try:
        await callback.message.edit_text(
            _appt_card_text(fresh),
            reply_markup=master_appt_actions_keyboard(appt_id, fresh["status"]),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await callback.answer(_STATUS_WORD.get(status, status))


# ─── Перенос записи мастером (FSM) ───────────────────────────────────────────


@router.callback_query(F.data.startswith("mappt_rs_"))
async def cb_mappt_rs_start(callback: CallbackQuery, state: FSMContext) -> None:
    """«↔ Перенести» из карточки записи. Callback `mappt_rs_<id>`.
    Показываем 7 дат вперёд."""
    parts = parse_callback(callback.data, "mappt_rs", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    try:
        appt_id = int(parts[0])
    except ValueError:
        await callback.answer()
        return

    loaded = await _load_master_appt(callback, appt_id)
    if loaded is None:
        return

    await state.set_state(MasterStates.reschedule_pick_date)
    await state.update_data(mrs_appt_id=appt_id)

    try:
        await callback.message.edit_text(
            "🔄 <b>Перенос записи</b>\n\nВыбери новую дату:",
            reply_markup=master_rs_dates_keyboard(appt_id),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(
    MasterStates.reschedule_pick_date, F.data.startswith("mappt_rsd_"),
)
async def cb_mappt_rs_pick_date(callback: CallbackQuery, state: FSMContext) -> None:
    """Мастер выбрал дату переноса. Считаем free slots и показываем."""
    parts = parse_callback(callback.data, "mappt_rsd", 2)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    try:
        appt_id = int(parts[0])
    except ValueError:
        await callback.answer()
        return
    date_str = parts[1]

    loaded = await _load_master_appt(callback, appt_id)
    if loaded is None:
        await state.clear()
        return
    master, appt = loaded

    # Считаем свободные слоты мастера. compute_free_slots учитывает расписание,
    # блокировки, другие scheduled записи — тот же код что у клиента и у админа.
    ctx, free_slots = await compute_free_slots(
        master["id"], date_str, appt["service_duration"],
    )
    if ctx.is_day_off:
        await callback.answer("В этот день ты не работаешь.", show_alert=True)
        return
    if not free_slots:
        await callback.answer("На этот день свободных слотов нет.", show_alert=True)
        return

    # Исключаем текущее время записи (если переносят в тот же день на то же
    # время — бессмысленный клик, но не ошибка). compute_free_slots уже
    # исключил этот слот как «занятый своей же записью» — значит он в free_slots
    # не появится. Но если дата та же — добавим пояснение.
    await state.set_state(MasterStates.reschedule_pick_time)
    try:
        await callback.message.edit_text(
            f"🔄 <b>Перенос записи</b>\n\n"
            f"Новая дата: <b>{_date_human(date_str)}</b>\n"
            f"Выбери время:",
            reply_markup=master_rs_times_keyboard(appt_id, date_str, free_slots),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(
    MasterStates.reschedule_pick_time, F.data.startswith("mappt_rst_"),
)
async def cb_mappt_rs_pick_time(callback: CallbackQuery, state: FSMContext) -> None:
    """Мастер выбрал время. Атомарный reschedule + push клиенту + push админам."""
    parts = parse_callback(callback.data, "mappt_rst", 3)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    try:
        appt_id = int(parts[0])
    except ValueError:
        await callback.answer()
        return
    new_date = parts[1]
    new_time = parts[2]

    loaded = await _load_master_appt(callback, appt_id)
    if loaded is None:
        await state.clear()
        return
    master, appt = loaded

    old_date = appt["date"]
    old_time = appt["time"]

    try:
        await reschedule_appointment(
            appt_id, new_date, new_time,
            service_duration=appt["service_duration"],
            master_id=master["id"],
        )
    except ValueError:
        # Гонка: слот заняли между списком и кликом.
        await callback.answer("⚠️ Этот слот уже занят. Выбери другой.", show_alert=True)
        return
    except Exception:
        logger.exception("reschedule_appointment упал (master self-serve)")
        await callback.answer("Не удалось перенести. Попробуй ещё раз.", show_alert=True)
        return

    await log_admin_action(
        admin_id=callback.from_user.id,
        action="master_reschedule",
        target_type="appointment",
        target_id=appt_id,
        details=(
            f"[{master['name']}] {appt['name']} — {appt['service_name']}: "
            f"{old_date} {old_time} → {new_date} {new_time}"
        ),
    )

    # Push клиенту.
    try:
        await notify_client(
            callback.bot, appt["user_id"], "rescheduled_by_master",
            {
                "master_name": master["name"].title(),
                "old_date": old_date,
                "old_time": old_time,
                "date": new_date,
                "time": new_time,
                "service_name": appt["service_name"],
            },
        )
    except Exception:
        logger.exception("notify_client(rescheduled_by_master) упал")

    # Push админам (если мастер сам не админ).
    if callback.from_user.id not in ADMIN_IDS:
        try:
            await broadcast_to_admins(
                callback.bot,
                f"🔄 <b>[{h(master['name'])}]</b> перенёс(ла) запись "
                f"{h(appt['name'])}:\n"
                f"было {old_date} {old_time} → стало <b>{new_date} {new_time}</b>.",
                log_context="master reschedule",
            )
        except Exception:
            logger.exception("broadcast_to_admins упал (перенос от мастера)")

    await state.clear()

    fresh = await get_appointment_by_id(appt_id)
    if fresh is None:
        await callback.answer()
        return
    try:
        await callback.message.edit_text(
            _appt_card_text(fresh),
            reply_markup=master_appt_actions_keyboard(appt_id, fresh["status"]),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await callback.answer(f"Перенесено на {new_date} {new_time}")


# ─── Push-уведомления ────────────────────────────────────────────────────────

@router.callback_query(F.data == "notif_dismiss")
async def cb_notif_dismiss(callback: CallbackQuery):
    """Мастерская копия admin.py::cb_notif_dismiss: удалить push-уведомление
    (новая запись / отмена / перенос) из чата. Admin-router под IsAdminFilter
    не пропускает не-админов, поэтому мастеру нужен свой обработчик."""
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass  # query протух — штатно
