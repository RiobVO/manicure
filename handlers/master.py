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
from aiogram.types import CallbackQuery, Message

from constants import MONTHS_RU, WEEKDAYS_FULL_RU, WEEKDAYS_SHORT_RU
from db import (
    get_master_appointments_today,
    get_master_appointments_upcoming,
    get_master_by_user_id,
    get_master_schedule,
)
from keyboards.inline import master_reply_keyboard
from utils.admin import IsMasterFilter
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


async def _nav(message: Message, text: str, parse_mode: str | None = None) -> None:
    """
    Удалить сообщение-тап (текст кнопки), отредактировать панель мастера или
    создать новую. Паттерн скопирован из handlers/admin.py::_nav,
    но без inline-markup (мастер не нажимает кнопок — read-only).
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
                    parse_mode=parse_mode,
                )
                return
            except TelegramBadRequest:
                try:
                    await message.bot.delete_message(chat_id, nav_id)
                except Exception:
                    pass
                clear_panel_msg_id(chat_id)

        sent = await message.bot.send_message(chat_id, text, parse_mode=parse_mode)
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


@router.message(StateFilter("*"), F.text == "📆 Моё расписание")
async def msg_schedule(message: Message, state: FSMContext) -> None:
    """Недельная сетка из master_schedule. Пустые weekdays / work_start=None → выходной."""
    await state.clear()
    master = await get_master_by_user_id(message.from_user.id)
    if master is None:
        return

    schedule = await get_master_schedule(master["id"])

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
    lines.append("\n<i>Изменить расписание — через администратора.</i>")

    await _nav(message, "\n".join(lines), parse_mode="HTML")


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
