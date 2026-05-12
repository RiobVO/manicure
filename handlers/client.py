import asyncio
import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from constants import MONTHS_RU, WEEKDAYS_SHORT_RU
from utils.callbacks import parse_callback
from utils.notifications import notify_master, broadcast_to_admins
from utils.timezone import now_local
from utils.ui import (
    DIVIDER_SOFT, DIVIDER_WHISPER,
    ARROW_DO, ARROW_SOFT, ARROW_BACK, REPEAT,
    price as fmt_price, duration as fmt_dur,
    date_soft,
    greeting_new, greeting_returning,
    booking_done_hero, booking_reminder_note,
    h,
)
from states import BookingStates
from db import (
    get_services, get_service_by_id,
    create_appointment,
    get_client_profile, save_client_profile,
    get_client_appointments, get_appointment_by_id,
    get_weekly_schedule,
    get_addons_for_service,
    get_active_masters, get_master,
    get_day_off_weekdays_for_master,
    get_all_masters_ratings,
)
from db.appointments import save_appointment_addons
from keyboards.inline import (
    services_keyboard, category_keyboard, dates_keyboard, times_keyboard,
    confirm_keyboard, admin_reply_keyboard, contact_keyboard,
    addons_keyboard, client_reply_keyboard, masters_keyboard,
)
from config import ADMIN_IDS
from utils.admin import is_admin, is_master
from utils.panel import set_reply_kb
from services.booking import (
    calculate_total_price,
    addon_names_for,
    resolve_active_master,
    compute_free_slots,
)

logger = logging.getLogger(__name__)
router = Router()

# Strong references на fire-and-forget таски: asyncio хранит только weak refs,
# без этого GC может собрать Task до завершения send_message (silent cancel).
_bg_tasks: set[asyncio.Task] = set()


# ─── Трекер последнего сообщения со списком услуг ────────────────────────────
# Нужен, чтобы reply-кнопка «записаться» не плодила дубликаты:
# перед отправкой нового списка удаляем предыдущий. Простой FIFO с лимитом.
_CLIENT_SERVICES_MSG_MAX = 500
_client_services_msg: dict[int, int] = {}


def _remember_services_msg(chat_id: int, msg_id: int) -> None:
    if len(_client_services_msg) >= _CLIENT_SERVICES_MSG_MAX:
        # Простой eviction: выкидываем самый ранний ключ (dict хранит порядок).
        for k in list(_client_services_msg)[: len(_client_services_msg) - _CLIENT_SERVICES_MSG_MAX + 1]:
            _client_services_msg.pop(k, None)
    _client_services_msg[chat_id] = msg_id


async def _cleanup_services_msg(bot, chat_id: int) -> None:
    """Удалить предыдущий список услуг, если был. Тихо, без шума при неудаче."""
    old_id = _client_services_msg.pop(chat_id, None)
    if old_id is None:
        return
    try:
        await bot.delete_message(chat_id, old_id)
    except TelegramBadRequest:
        pass


# ─── Выбор категории (ручки/ножки) и список услуг в ней ──────────────────────

CATEGORY_PROMPT = "<i>ручки или ножки?</i>"
SERVICES_BY_CATEGORY_PROMPT = "<i>что красим?</i>"
NO_SERVICES_MSG = "<i>пока нет доступных услуг.</i>\n\n<i>скоро вернёмся.</i>"


async def _send_category_picker(message: Message, state: FSMContext) -> None:
    """Первый экран записи — выбор ручек/ножек. Отправляет новое сообщение."""
    services = await get_services(active_only=True)
    if not services:
        await message.answer(NO_SERVICES_MSG, parse_mode="HTML")
        return
    sent = await message.answer(
        CATEGORY_PROMPT,
        reply_markup=category_keyboard(),
        parse_mode="HTML",
    )
    _remember_services_msg(message.chat.id, sent.message_id)
    await state.set_state(BookingStates.choose_category)


async def _edit_to_category_picker(callback: CallbackQuery, state: FSMContext) -> None:
    """То же, но через edit_text — не плодит новые сообщения при навигации."""
    services = await get_services(active_only=True)
    if not services:
        try:
            await callback.message.edit_text(NO_SERVICES_MSG, parse_mode="HTML")
        except TelegramBadRequest:
            pass
        return
    _remember_services_msg(callback.message.chat.id, callback.message.message_id)
    try:
        await callback.message.edit_text(
            CATEGORY_PROMPT,
            reply_markup=category_keyboard(),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await state.set_state(BookingStates.choose_category)


def _date_human(date_str: str) -> str:
    """Конвертирует YYYY-MM-DD → '15 января, пт'."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.day} {MONTHS_RU[dt.month - 1]}, {WEEKDAYS_SHORT_RU[dt.weekday()]}"
    except ValueError:
        return date_str


async def _day_off_weekdays() -> frozenset[int]:
    """Множество номеров дней недели (0=Пн), которые помечены выходными."""
    schedule = await get_weekly_schedule()
    return frozenset(wd for wd, row in schedule.items() if row["work_start"] is None)


async def _show_master_step(
    callback: CallbackQuery,
    state: FSMContext,
    service_header: str,
) -> None:
    """
    Показывает выбор мастера. Если мастер один — пропускает шаг и сразу переходит к датам.
    service_header — уже сформированная строка с названием/ценой услуги.
    """
    masters = await get_active_masters()
    if not masters:
        # мастера не заведены — пропускаем шаг, идём к датам без привязки к мастеру
        day_off_weekdays = await _day_off_weekdays()
        try:
            await callback.message.edit_text(
                f"{service_header}\n\n<i>выбери дату.</i>",
                reply_markup=dates_keyboard(day_off_weekdays),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
        await state.set_state(BookingStates.choose_date)
        await callback.answer()
        return

    if len(masters) == 1:
        master = masters[0]
        await state.update_data(master_id=master["id"], master_name=master["name"])
        day_off_weekdays = await get_day_off_weekdays_for_master(master["id"])
        try:
            await callback.message.edit_text(
                f"{service_header}\n\n<i>выбери дату.</i>",
                reply_markup=dates_keyboard(day_off_weekdays),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
        await state.set_state(BookingStates.choose_date)
        await callback.answer()
        return

    ratings = await get_all_masters_ratings()
    try:
        await callback.message.edit_text(
            f"{service_header}\n\n<i>кто тебя принимает?</i>",
            reply_markup=masters_keyboard(masters, ratings),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await state.set_state(BookingStates.choose_master)
    await callback.answer()


@router.message(F.text.regexp(r"^/start(?:\s|$)"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()

    # /start <payload> → deep-link attribution (Phase 2 v.4).
    # Парсим вручную: CommandObject конфликтует с F.text.startswith, а
    # большинство кликов по /start будет без payload.
    parts = (message.text or "").split(maxsplit=1)
    payload = parts[1].strip() if len(parts) == 2 else ""
    if payload:
        from db.traffic import (
            get_source_by_code,
            normalize_code,
            set_client_source_if_empty,
        )
        code = normalize_code(payload)
        if code and not is_admin(message.from_user.id):
            src = await get_source_by_code(code)
            if src:
                try:
                    await set_client_source_if_empty(
                        message.from_user.id, src["code"]
                    )
                except Exception:
                    logger.exception("не удалось атрибутировать source=%s user=%s",
                                     src["code"], message.from_user.id)

    # is_admin() покрывает env ADMIN_IDS ∪ DB-админов из /admin-management,
    # иначе DB-админ на /start падает в клиентский флоу, хотя везде остальном — админ.
    if is_admin(message.from_user.id):
        try:
            await message.delete()
        except TelegramBadRequest:
            pass  # сообщение уже удалено или недоступно
        # Сохраняем reply keyboard для этого чата
        set_reply_kb(message.chat.id, admin_reply_keyboard())
        # Отправляем ТОЛЬКО reply keyboard — без дополнительного сообщения
        await message.answer("👑 <b>Панель администратора</b>", reply_markup=admin_reply_keyboard(), parse_mode="HTML")
        return

    # Мастер (user_id привязан к активной записи в masters) — свой кабинет.
    # Late import handlers.master, чтобы избежать потенциального circular import
    # на уровне модуля (client.py грузится при импорте хендлеров в bot.py).
    if is_master(message.from_user.id):
        from handlers.master import show_master_cabinet_entry
        await show_master_cabinet_entry(message, state)
        return

    # Показать reply-клавиатуру тихо (невидимый разделитель — иначе сообщение нельзя отправить)
    await message.answer("\u2063", reply_markup=client_reply_keyboard())

    # Проверить: возвращается клиент или новый
    profile = await get_client_profile(message.from_user.id)
    last_appts = await get_client_appointments(message.from_user.id) if profile else []
    last_completed = next((a for a in last_appts if a["status"] == "completed"), None)

    if profile and last_completed:
        # Возвращающийся клиент — тёплое приветствие + быстрые действия
        days_since = (now_local().date() - datetime.strptime(last_completed["date"], "%Y-%m-%d").date()).days
        master_name = None
        if last_completed.get("master_id"):
            m = await get_master(last_completed["master_id"])
            if m:
                master_name = m["name"].title()

        greet = greeting_returning(
            name=profile["name"],
            days_ago=days_since,
            service=last_completed["service_name"],
            master=master_name,
        )
        await message.answer(greet, parse_mode="HTML")

        # Небольшая пауза перед меню — воздух между репликами
        await asyncio.sleep(0.6)

        svc_name_short = last_completed["service_name"][:45]
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{REPEAT}  повторить · {svc_name_short}",
                callback_data=f"quick_rebook_{last_completed['id']}",
            )],
            [InlineKeyboardButton(text=f"{ARROW_SOFT} выбрать другое", callback_data="client_restart")],
        ])
        await message.answer(
            f"<i>что сегодня?</i>\n{DIVIDER_WHISPER}",
            reply_markup=kb,
            parse_mode="HTML",
        )
        await state.set_state(BookingStates.choose_service)
        return

    # Новый клиент — hero-приветствие + выбор категории (ручки/ножки)
    await message.answer(greeting_new(), parse_mode="HTML")
    await asyncio.sleep(0.5)
    await _send_category_picker(message, state)


# ─── BOOKING FLOW ────────────────────────────────────────────────────────────

@router.callback_query(BookingStates.choose_service, F.data.startswith("service_"))
async def choose_service(callback: CallbackQuery, state: FSMContext):
    parts = parse_callback(callback.data, "service", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    service_id = int(parts[0])
    service = await get_service_by_id(service_id)

    if service is None or not service["is_active"]:
        logger.warning("Unknown/inactive service_id=%s from user_id=%s", service_id, callback.from_user.id)
        await callback.answer("Услуга недоступна. Начните заново: /start", show_alert=True)
        await state.clear()
        return

    await state.update_data(
        service_id=service_id,
        service_name=service["name"],
        service_price=service["price"],
        service_duration=service["duration"],
        selected_addons=[],
    )

    # Карточка услуги в blockquote — описание идёт в текст, фото не отправляем
    desc = service.get("description")
    desc_line = f"\n\n<i>{h(desc)}</i>" if desc else ""
    service_card = (
        f"<blockquote>"
        f"<b><i>{h(service['name'].lower())}</i></b>"
        f"{desc_line}\n\n"
        f"{DIVIDER_SOFT}\n\n"
        f"<i>длительность</i>   <code>{fmt_dur(service['duration'])}</code>\n"
        f"<i>стоимость</i>      <code>{fmt_price(service['price'])}</code>"
        f"</blockquote>"
    )

    # Проверяем доп. опции для этой услуги
    addons = await get_addons_for_service(service_id)
    if addons:
        try:
            await callback.message.edit_text(
                f"{service_card}\n\n<i>можно добавить:</i>",
                reply_markup=addons_keyboard(addons),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
        await state.set_state(BookingStates.choose_addons)
        await callback.answer()
        return

    await _show_master_step(callback, state, service_card)


@router.callback_query(BookingStates.choose_addons, F.data.startswith("addon_"))
async def cb_toggle_addon(callback: CallbackQuery, state: FSMContext):
    """Переключить выбор доп. опции (toggle)."""
    parts = parse_callback(callback.data, "addon", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    addon_id = int(parts[0])
    data = await state.get_data()
    selected: list[int] = data.get("selected_addons", [])

    if addon_id in selected:
        selected.remove(addon_id)
    else:
        selected.append(addon_id)
    await state.update_data(selected_addons=selected)

    addons = await get_addons_for_service(data["service_id"])
    try:
        total = calculate_total_price(data["service_price"], selected, addons)
        service_card = (
            f"<blockquote>"
            f"<b><i>{h(data['service_name'].lower())}</i></b>\n\n"
            f"{DIVIDER_SOFT}\n\n"
            f"<i>длительность</i>   <code>{fmt_dur(data['service_duration'])}</code>\n"
            f"<i>стоимость</i>      <code>{fmt_price(total)}</code>"
            f"</blockquote>"
        )
        await callback.message.edit_text(
            f"{service_card}\n\n<i>можно добавить:</i>",
            reply_markup=addons_keyboard(addons, set(selected)),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(BookingStates.choose_addons, F.data == "addons_done")
async def cb_addons_done(callback: CallbackQuery, state: FSMContext):
    """Завершить выбор доп. опций — перейти к дате."""
    data = await state.get_data()
    selected: list[int] = data.get("selected_addons", [])

    # Подсчитать итоговую цену и сформировать список названий
    addons = await get_addons_for_service(data["service_id"])
    final_price = calculate_total_price(data["service_price"], selected, addons)
    addon_names = addon_names_for(selected, addons)

    await state.update_data(
        service_price=final_price,
        addon_names=addon_names,
    )

    addon_line = (f"<i>+ {h(', '.join(addon_names).lower())}</i>\n\n") if addon_names else ""
    header = (
        f"<blockquote>"
        f"<b><i>{h(data['service_name'].lower())}</i></b>\n\n"
        f"{addon_line}"
        f"{DIVIDER_SOFT}\n\n"
        f"<i>длительность</i>   <code>{fmt_dur(data['service_duration'])}</code>\n"
        f"<i>стоимость</i>      <code>{fmt_price(final_price)}</code>"
        f"</blockquote>"
    )
    await _show_master_step(callback, state, header)


@router.callback_query(BookingStates.choose_master, F.data.startswith("master_"))
async def choose_master(callback: CallbackQuery, state: FSMContext):
    parts = parse_callback(callback.data, "master", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    master_id = int(parts[0])
    master = await get_master(master_id)
    if not master or not master["is_active"]:
        await callback.answer("Мастер недоступен. Выберите другого.", show_alert=True)
        return

    await state.update_data(master_id=master_id, master_name=master["name"])
    data = await state.get_data()

    # Собираем полный текст: blockquote услуги + blockquote мастера + подсказка
    addon_line = (f"<i>+ {h(', '.join(data['addon_names']).lower())}</i>\n\n") if data.get("addon_names") else ""
    service_card = (
        f"<blockquote>"
        f"<b><i>{h(data['service_name'].lower())}</i></b>\n\n"
        f"{addon_line}"
        f"{DIVIDER_SOFT}\n\n"
        f"<i>длительность</i>   <code>{fmt_dur(data['service_duration'])}</code>\n"
        f"<i>стоимость</i>      <code>{fmt_price(data['service_price'])}</code>"
        f"</blockquote>"
    )
    bio_line = f"\n\n<i>{h(master['bio'])}</i>" if master.get("bio") else ""
    master_card = (
        f"<blockquote>"
        f"<b><i>{h(master['name'].title())}</i></b>"
        f"{bio_line}"
        f"</blockquote>"
    )

    day_off_weekdays = await get_day_off_weekdays_for_master(master_id)
    try:
        await callback.message.edit_text(
            f"{service_card}\n\n"
            f"{master_card}\n\n"
            f"<i>выбери дату.</i>",
            reply_markup=dates_keyboard(day_off_weekdays),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await state.set_state(BookingStates.choose_date)
    await callback.answer()


@router.callback_query(BookingStates.choose_date, F.data.startswith("date_"))
async def choose_date(callback: CallbackQuery, state: FSMContext):
    parts = parse_callback(callback.data, "date", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    date_str = parts[0]
    data = await state.get_data()
    duration = data["service_duration"]
    master_id: int | None = data.get("master_id")

    # day_off_weekdays нужен для перерисовки календаря на ошибках — получаем отдельно,
    # т.к. compute_free_slots возвращает контекст только на одну дату.
    if master_id is not None:
        day_off_weekdays = await get_day_off_weekdays_for_master(master_id)
    else:
        day_off_weekdays = await _day_off_weekdays()

    ctx, free_slots = await compute_free_slots(master_id, date_str, duration)

    if ctx.is_day_off:
        try:
            await callback.message.edit_text(
                f"<i>в этот день не работаем.</i>\n\n"
                f"<i>выбери другую дату.</i>",
                reply_markup=dates_keyboard(day_off_weekdays),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
        await callback.answer()
        return

    if not free_slots:
        try:
            await callback.message.edit_text(
                f"<i>на этот день всё занято.</i>\n\n"
                f"<i>попробуй другую дату.</i>",
                reply_markup=dates_keyboard(day_off_weekdays),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
        await callback.answer()
        return

    await state.update_data(date=date_str)
    try:
        await callback.message.edit_text(
            f"<b><i>{date_soft(date_str)}</i></b>\n\n"
            f"<i>выбери время.</i>",
            reply_markup=times_keyboard(free_slots),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await state.set_state(BookingStates.choose_time)
    await callback.answer()


@router.callback_query(BookingStates.choose_time, F.data.startswith("time_"))
async def choose_time(callback: CallbackQuery, state: FSMContext):
    parts = parse_callback(callback.data, "time", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    time_str = parts[0]
    await state.update_data(time=time_str)

    profile = await get_client_profile(callback.from_user.id)
    if profile:
        try:
            await callback.message.edit_text(
                f"<i>подтвердите данные</i>\n"
                f"{DIVIDER_WHISPER}\n\n"
                f"<b>{profile['name']}</b>  ·  <code>{profile['phone']}</code>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=f"{ARROW_DO} всё верно", callback_data="use_saved_profile")],
                    [InlineKeyboardButton(text=f"{ARROW_SOFT} изменить", callback_data="change_profile")],
                ]),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
        await state.set_state(BookingStates.confirm_profile)
    else:
        try:
            await callback.message.edit_text(
                f"<i>как тебя зовут?</i>",
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
        await state.set_state(BookingStates.get_name)
    await callback.answer()


@router.callback_query(BookingStates.confirm_profile, F.data == "use_saved_profile")
async def use_saved_profile(callback: CallbackQuery, state: FSMContext):
    profile = await get_client_profile(callback.from_user.id)
    if not profile:
        try:
            await callback.message.edit_text(
                f"<i>как тебя зовут?</i>",
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
        await state.set_state(BookingStates.get_name)
        await callback.answer()
        return

    await state.update_data(name=profile["name"], phone=profile["phone"])
    data = await state.get_data()
    addon_line = (f"\n<i>+ {h(', '.join(data['addon_names']).lower())}</i>") if data.get("addon_names") else ""
    master_line = (f"\n<i>мастер · {h(data['master_name'].title())}</i>") if data.get("master_name") else ""
    summary = (
        f"<blockquote>"
        f"<b><i>всё так?</i></b>\n\n"
        f"{DIVIDER_SOFT}\n\n"
        f"<b>{h(data['service_name'].lower())}</b>"
        f"{addon_line}"
        f"{master_line}\n\n"
        f"<i>когда</i>       <code>{date_soft(data['date'])} · {data['time']}</code>\n"
        f"<i>стоимость</i>   <code>{fmt_price(data['service_price'])}</code>\n\n"
        f"<i>{h(data['name'])} · {h(data['phone'])}</i>"
        f"</blockquote>"
    )
    try:
        await callback.message.edit_text(
            summary,
            reply_markup=confirm_keyboard(),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await state.set_state(BookingStates.confirm)
    await callback.answer()


@router.callback_query(BookingStates.confirm_profile, F.data == "change_profile")
async def change_profile(callback: CallbackQuery, state: FSMContext):
    try:
        await callback.message.edit_text(
            f"<i>как тебя зовут?</i>",
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await state.set_state(BookingStates.get_name)
    await callback.answer()


_RESERVED_NAMES = frozenset({"записаться", "мои записи"})


@router.message(BookingStates.get_name)
async def get_name(message: Message, state: FSMContext):
    name = message.text.strip() if message.text else ""
    if not name or len(name) < 2 or len(name) > 64 or name.lower() in _RESERVED_NAMES or name.startswith("/"):
        # Reserved: лейблы reply-клавиатуры — если клиент тыкнул их вместо
        # того чтобы ввести имя, не сохраняем «записаться» как имя в профиль.
        await message.answer(
            f"<i>имя нужно от 2 до 64 букв.</i>\n"
            f"<i>попробуй ещё раз:</i>",
            parse_mode="HTML",
        )
        return
    await state.update_data(name=name)
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    phone_prompt = await message.answer(
        f"<i>поделись номером телефона.</i>\n\n"
        f"<i>так быстрее, чем набирать.</i>",
        reply_markup=contact_keyboard(),
        parse_mode="HTML",
    )
    await state.update_data(_phone_prompt_msg_id=phone_prompt.message_id)
    await state.set_state(BookingStates.get_phone)


@router.message(BookingStates.get_phone, F.contact)
async def get_phone(message: Message, state: FSMContext):
    contact = message.contact
    # Telegram проставляет contact.user_id только для ОТПРАВИТЕЛЯ своего контакта.
    # Если пользователь шарит чужой контакт (из адресной книги) — user_id=None
    # или != from_user.id. Защита от: (а) случайного выбора контакта мамы/мужа,
    # (б) намеренной записи чужого человека.
    if contact.user_id is None or contact.user_id != message.from_user.id:
        await message.answer(
            "<i>поделись своим номером — кнопкой ниже.</i>",
            reply_markup=contact_keyboard(),
            parse_mode="HTML",
        )
        return
    phone = contact.phone_number
    await state.update_data(phone=phone)

    # Удаляем системное сообщение с контактом — в чате не должно болтаться
    # личное инфо и клавиатура «отправить номер».
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    data = await state.get_data()
    addon_line = (f"\n<i>+ {h(', '.join(data['addon_names']).lower())}</i>") if data.get("addon_names") else ""
    master_line = (f"\n<i>мастер · {h(data['master_name'].title())}</i>") if data.get("master_name") else ""
    summary = (
        f"<blockquote>"
        f"<b><i>всё так?</i></b>\n\n"
        f"{DIVIDER_SOFT}\n\n"
        f"<b>{h(data['service_name'].lower())}</b>"
        f"{addon_line}"
        f"{master_line}\n\n"
        f"<i>когда</i>       <code>{date_soft(data['date'])} · {data['time']}</code>\n"
        f"<i>стоимость</i>   <code>{fmt_price(data['service_price'])}</code>\n\n"
        f"<i>{h(data['name'])} · {h(data['phone'])}</i>"
        f"</blockquote>"
    )

    # summary — трекаем для удаления после подтверждения; reply-keyboard
    # возвращаем к обычной (иначе после contact-kb чат остаётся без кнопок).
    summary_msg = await message.answer(
        summary,
        reply_markup=client_reply_keyboard(),
        parse_mode="HTML",
    )
    await state.update_data(_summary_msg_id=summary_msg.message_id)

    await message.answer(
        "<i>подтверди, если всё верно.</i>",
        reply_markup=confirm_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(BookingStates.confirm)


@router.callback_query(BookingStates.confirm, F.data == "confirm_yes")
async def confirm_yes(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    master_id: int | None = data.get("master_id")

    # Финальная проверка мастера: между выбором и подтверждением админ мог
    # деактивировать/удалить мастера. Запись к «призраку» не создаём.
    if master_id is not None and await resolve_active_master(master_id) is None:
        try:
            await callback.message.edit_text(
                "<i>мастер больше недоступен.</i>\n<i>начни заново: /start</i>",
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
        await state.clear()
        await callback.answer()
        return

    try:
        appt_id = await create_appointment(
            user_id=callback.from_user.id,
            name=data["name"],
            phone=data["phone"],
            service_id=data["service_id"],
            service_name=data["service_name"],
            service_duration=data["service_duration"],
            service_price=data["service_price"],
            date=data["date"],
            time=data["time"],
            master_id=master_id,
        )
    except ValueError as e:
        try:
            _, free_slots = await compute_free_slots(
                master_id, data["date"], data["service_duration"],
            )
            await callback.message.edit_text(
                f"<i>это время уже заняли.</i>\n\n"
                f"<i>выбери другое:</i>",
                reply_markup=times_keyboard(free_slots),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
        await state.set_state(BookingStates.choose_time)
        await callback.answer()
        return
    except Exception:
        logger.exception("DB write failed for user_id=%s", callback.from_user.id)
        try:
            await callback.message.edit_text(
                "<i>что-то пошло не так.</i>\n<i>попробуй /start.</i>",
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
        await state.clear()
        await callback.answer()
        return

    await save_client_profile(callback.from_user.id, data["name"], data["phone"])

    # FSM-state очищаем ПРЯМО СЕЙЧАС, до любых UI-ошибок и внешних вызовов.
    # Раньше state.clear() стоял в самом конце — если любой из message.answer
    # падал (например, TelegramBadRequest на битом payment URL), до clear()
    # управление не доходило, и BookingStates.confirm оставался в Redis.
    # Следующий текст клиента попадал в confirm_text_fallback → «используй кнопки выше».
    await state.clear()

    # Сохранение доп. опций
    addon_ids = data.get("selected_addons", [])
    if addon_ids:
        try:
            await save_appointment_addons(appt_id, addon_ids)
        except Exception:
            logger.error("Ошибка сохранения аддонов для appointment_id=%s", appt_id, exc_info=True)

    # Уведомления админа и мастера — в фон. Клиенту неинтересно что они дошли;
    # ему важно увидеть «ты записана» без секундной задержки на TG API.
    appt_date = datetime.strptime(data['date'], "%Y-%m-%d")
    date_str = f"{appt_date.day} {MONTHS_RU[appt_date.month - 1]}"
    notif_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Принято", callback_data="notif_dismiss"),
        InlineKeyboardButton(text="📒 Все записи", callback_data="notif_all_appointments"),
    ]])

    async def _bg_admin_broadcast() -> None:
        try:
            # h() на user-controlled полях (name, phone) и admin-controlled
            # (service_name): одно "<" ломает TG parse HTML и рассылка молча теряется.
            await broadcast_to_admins(
                callback.bot,
                f"🔔 <b>Новая запись:</b> {date_str} в <b>{data['time']}</b>\n"
                f"💅 {h(data['service_name'])} — {h(data['name'])}\n"
                f"📞 {h(data['phone'])}",
                reply_markup=notif_kb,
                log_context="new booking",
            )
        except Exception:
            logger.exception("Failed to notify admin about new booking")

    async def _bg_master_notify() -> None:
        if not master_id:
            return
        try:
            await notify_master(
                callback.bot, master_id, "new_booking",
                {"date": data["date"], "time": data["time"],
                 "client_name": data["name"], "service_name": data["service_name"]},
            )
        except Exception:
            logger.error("Ошибка уведомления мастера", exc_info=True)

    for coro in (_bg_admin_broadcast(), _bg_master_notify()):
        t = asyncio.create_task(coro)
        _bg_tasks.add(t)
        t.add_done_callback(_bg_tasks.discard)

    # Уборка transient-сообщений флоу: "как тебя зовут?" (последнее состояние
    # цепочки edit_text), "поделись номером", summary "всё так?". Оставляем
    # в чате только итог — hero + blockquote + напоминалка + (опц.) оплата.
    flow_msg_id = _client_services_msg.pop(callback.message.chat.id, None)
    for msg_id in (flow_msg_id, data.get("_phone_prompt_msg_id"), data.get("_summary_msg_id")):
        if not msg_id or msg_id == callback.message.message_id:
            continue
        try:
            await callback.bot.delete_message(callback.message.chat.id, msg_id)
        except TelegramBadRequest:
            pass

    addon_line_done = (f"\n<i>+ {h(', '.join(data.get('addon_names', [])).lower())}</i>") if data.get("addon_names") else ""
    master_line_done = (f"\n<i>мастер · {h(data['master_name'].title())}</i>") if data.get("master_name") else ""

    # 1. Hero — акцент на успехе записи. Идёт СРАЗУ после create_appointment,
    # без ожидания уведомлений админа/мастера.
    try:
        await callback.message.edit_text(
            booking_done_hero(data['name']),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass

    # 2. Детальная карточка в blockquote — «жду тебя»
    await callback.message.answer(
        f"<blockquote>"
        f"<b><i>{h(data['name'])}, жду тебя.</i></b>\n\n"
        f"{DIVIDER_SOFT}\n\n"
        f"<b>{h(data['service_name'].lower())}</b>"
        f"{addon_line_done}"
        f"{master_line_done}\n\n"
        f"<i>когда</i>         <code>{date_soft(data['date'])} · {data['time']}</code>\n"
        f"<i>длительность</i>  <code>{fmt_dur(data['service_duration'])}</code>\n"
        f"<i>к оплате</i>      <code>{fmt_price(data['service_price'])}</code>"
        f"</blockquote>",
        parse_mode="HTML",
    )

    # 3. Мягкое напоминание + «до встречи ✧».
    # reply_markup здесь возвращает нижнюю панель «записаться | мои записи»:
    # summary_msg, на котором она висела, был удалён выше как transient,
    # а hero/blockquote шли через edit_text и answer без reply_markup,
    # поэтому клиент остался без reply-клавиатуры до этого момента.
    await callback.message.answer(
        booking_reminder_note(),
        reply_markup=client_reply_keyboard(),
        parse_mode="HTML",
    )

    # 4. Ссылка на оплату — в самом конце, как CTA после полного подтверждения.
    # Приоритет: PAYMENT_PROVIDER (click/payme) → legacy PAYMENT_URL → ничего.
    from keyboards.inline import payment_keyboard
    from utils.payments import get_provider

    pay_url: str | None = None
    provider = get_provider()
    if provider is not None:
        try:
            invoice = await provider.create_invoice(
                appt_id=appt_id,
                amount_uzs=data["service_price"],
                phone=data["phone"],
            )
            from db.payments import attach_invoice
            await attach_invoice(
                appt_id, provider.name, invoice.invoice_id, invoice.pay_url
            )
            pay_url = invoice.pay_url
        except Exception:
            # Создание инвойса провалилось, но запись уже сохранена — клиент
            # не страдает. Ошибка уйдёт в error-канал через @dp.errors.
            logger.exception("create_invoice failed for appt=%s", appt_id)

    if pay_url is None:
        # Fallback на legacy PAYMENT_URL — для салонов без интеграции провайдера.
        from config import PAYMENT_URL
        if PAYMENT_URL:
            pay_url = (
                PAYMENT_URL
                .replace("{amount}", str(data["service_price"]))
                .replace("{appt_id}", str(appt_id))
            )

    pay_kb = payment_keyboard(pay_url)
    if pay_kb:
        await callback.message.answer(
            "<i>ссылка на оплату:</i>",
            reply_markup=pay_kb,
            parse_mode="HTML",
        )

    await callback.answer()


@router.callback_query(BookingStates.confirm, F.data == "confirm_no")
async def confirm_no(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.edit_text(
            f"<i>хорошо. ничего не создаём.</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=f"{ARROW_BACK} к услугам", callback_data="client_restart"),
            ]]),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.message(BookingStates.get_phone)
async def get_phone_wrong(message: Message):
    await message.answer(
        "<i>номер нужен через кнопку ниже.</i>",
        reply_markup=contact_keyboard(),
        parse_mode="HTML",
    )


@router.message(BookingStates.confirm, F.text.in_({"записаться", "/start"}))
async def confirm_escape_to_booking(message: Message, state: FSMContext):
    """
    Escape-hatch для клиентов, у которых FSM залип в BookingStates.confirm
    (прошлый баг с падением confirm_yes на битом payment URL). Без этого
    их любой текст ловил confirm_text_fallback вечно.
    """
    await state.clear()
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    await _cleanup_services_msg(message.bot, message.chat.id)
    await _send_category_picker(message, state)


@router.message(BookingStates.confirm)
async def confirm_text_fallback(message: Message):
    await message.answer("<i>используй кнопки выше.</i>", parse_mode="HTML")


@router.callback_query(F.data == "client_restart")
async def cb_client_restart(callback: CallbackQuery, state: FSMContext):
    """«выбрать другое» у возвращающегося клиента → обратно к выбору категории."""
    await state.clear()
    await _edit_to_category_picker(callback, state)
    await callback.answer()


@router.callback_query(F.data.in_({"cat_hands", "cat_feet"}))
async def cb_pick_category(callback: CallbackQuery, state: FSMContext):
    """Клиент выбрал категорию — показываем услуги в ней с ценами."""
    category = "hands" if callback.data == "cat_hands" else "feet"
    services = await get_services(active_only=True, category=category)
    if not services:
        # В этой категории пусто — возвращаем клиента на выбор категории
        # с короткой пометкой. Не даём ему тупика.
        try:
            await callback.message.edit_text(
                f"<i>тут пока пусто. попробуй другую:</i>\n\n{CATEGORY_PROMPT}",
                reply_markup=category_keyboard(),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
        await callback.answer()
        return
    _remember_services_msg(callback.message.chat.id, callback.message.message_id)
    try:
        await callback.message.edit_text(
            SERVICES_BY_CATEGORY_PROMPT,
            reply_markup=services_keyboard(services, with_back=True),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await state.set_state(BookingStates.choose_service)
    await callback.answer()


@router.callback_query(F.data == "cat_back")
async def cb_category_back(callback: CallbackQuery, state: FSMContext):
    """«‹ назад» из списка услуг — возвращаемся к выбору категории."""
    await state.clear()
    await _edit_to_category_picker(callback, state)
    await callback.answer()


@router.message(F.text == "записаться")
async def btn_book(message: Message, state: FSMContext):
    """Кнопка reply-клавиатуры — сбрасывает FSM и ведёт на выбор категории."""
    await state.clear()

    # Убрать само сообщение «записаться» и предыдущий список услуг, если он висит.
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    await _cleanup_services_msg(message.bot, message.chat.id)

    await _send_category_picker(message, state)


@router.callback_query(F.data.regexp(r"^quick_rebook_(\d+)$"))
async def cb_quick_rebook(callback: CallbackQuery, state: FSMContext):
    """Быстрая повторная запись — берёт услугу из последней завершённой записи."""
    parts = parse_callback(callback.data, "quick_rebook", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    appt_id = int(parts[0])
    appt = await get_appointment_by_id(appt_id)

    if not appt or appt["user_id"] != callback.from_user.id:
        await callback.answer("Запись не найдена.", show_alert=True)
        return

    # Проверяем, что услуга ещё активна
    service = await get_service_by_id(appt["service_id"])
    if not service or not service.get("is_active"):
        await callback.answer("Эта услуга больше не доступна.", show_alert=True)
        return

    await state.clear()
    await state.update_data(
        service_id=service["id"],
        service_name=service["name"],
        service_duration=service["duration"],
        service_price=service["price"],
        selected_addons=[],
    )

    profile = await get_client_profile(callback.from_user.id)
    if profile:
        await state.update_data(name=profile["name"], phone=profile["phone"])

    header = (
        f"<blockquote>"
        f"<b><i>повторяем</i></b>\n\n"
        f"{DIVIDER_SOFT}\n\n"
        f"<b>{h(service['name'].lower())}</b>\n"
        f"<i>длительность</i>   <code>{fmt_dur(service['duration'])}</code>\n"
        f"<i>стоимость</i>      <code>{fmt_price(service['price'])}</code>"
        f"</blockquote>"
    )
    await _show_master_step(callback, state, header)


# Мастерские кнопки, сохранившиеся в чате у пользователя, которого админ
# деактивировал как мастера. IsMasterFilter в master.router их больше не
# пропускает — ловим здесь и мягко переключаем на клиентский режим,
# чтобы не падать в fallback_message → каталог услуг с мастерской клавиатурой.
_EX_MASTER_BUTTON_TEXTS = frozenset({"📋 Сегодня", "📅 Мои записи", "📆 Моё расписание"})


@router.message(F.text.in_(_EX_MASTER_BUTTON_TEXTS))
async def ex_master_button(message: Message, state: FSMContext):
    await state.clear()
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    # Невидимый символ \u2063 — единственный способ послать update клавиатуры
    # без видимого текста (Telegram не шлёт пустые сообщения).
    await message.answer("\u2063", reply_markup=client_reply_keyboard())
    await _send_category_picker(message, state)


@router.message()
async def fallback_message(message: Message, state: FSMContext):
    if await state.get_state() is None:
        await _send_category_picker(message, state)
