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
from db import (
    add_master_day_off,
    count_master_scheduled_on_date,
    delete_master_day_off,
    get_future_master_day_offs,
    get_master_appointments_today,
    get_master_appointments_upcoming,
    get_master_by_user_id,
    get_master_schedule,
)
from keyboards.inline import (
    master_back_to_schedule_keyboard,
    master_day_off_dates_keyboard,
    master_day_off_remove_keyboard,
    master_reply_keyboard,
    master_schedule_menu_keyboard,
)
from utils.admin import IsMasterFilter
from utils.callbacks import parse_callback
from utils.notifications import broadcast_to_admins
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

@router.message(StateFilter("*"), F.text == "📋 Сегодня")
async def msg_today(message: Message, state: FSMContext) -> None:
    """Сегодняшние записи: scheduled + completed + no_show. Без cancelled."""
    await state.clear()
    master = await get_master_by_user_id(message.from_user.id)
    if master is None:
        return

    date_str = now_local().strftime("%Y-%m-%d")
    appointments = await get_master_appointments_today(master["id"], date_str)

    if not appointments:
        await _nav(
            message,
            f"📋 <b>Сегодня, {_date_human(date_str)}</b>\n\n"
            f"<i>Записей нет. Хорошего дня.</i>",
            parse_mode="HTML",
        )
        return

    lines = [f"📋 <b>Сегодня, {_date_human(date_str)}</b>"]
    for a in appointments:
        icon = _STATUS_ICON.get(a["status"], "·")
        lines.append(
            f"\n{icon} <b>{a['time']}</b> — {h(a['name'])}\n"
            f"   💅 {h(a['service_name'])} ({_duration_str(a['service_duration'])})\n"
            f"   📞 {h(a['phone'])}"
        )

    await _nav(message, "\n".join(lines), parse_mode="HTML")


@router.message(StateFilter("*"), F.text == "📅 Мои записи")
async def msg_upcoming(message: Message, state: FSMContext) -> None:
    """Ближайшие scheduled на сегодня и вперёд, до 30 штук, группировка по дате."""
    await state.clear()
    master = await get_master_by_user_id(message.from_user.id)
    if master is None:
        return

    today = now_local().strftime("%Y-%m-%d")
    appointments = await get_master_appointments_upcoming(master["id"], today, limit=30)

    if not appointments:
        await _nav(
            message,
            "📅 <b>Твои ближайшие записи</b>\n\n<i>Пока ничего запланировано.</i>",
            parse_mode="HTML",
        )
        return

    lines = ["📅 <b>Твои ближайшие записи</b>"]
    current_date = None
    for a in appointments:
        if a["date"] != current_date:
            current_date = a["date"]
            lines.append(f"\n<b>—— {_date_human(current_date)} ——</b>")
        lines.append(
            f"🕐 <b>{a['time']}</b> — {h(a['name'])} · {h(a['service_name'])} · 📞 {h(a['phone'])}"
        )

    if len(appointments) == 30:
        lines.append("\n<i>... показаны первые 30. Остальные — позже.</i>")

    await _nav(message, "\n".join(lines), parse_mode="HTML")


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
