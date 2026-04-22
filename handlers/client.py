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


async def _send_category_picker(
    message: Message,
    state: FSMContext,
    user_id: int | None = None,
) -> None:
    """Первый экран записи — выбор ручек/ножек. Отправляет новое сообщение.
    user_id явно — если message это callback.message (from_user = бот),
    вызывающий обязан передать реальный user_id клиента."""
    from utils.i18n import t
    from db import get_user_lang
    uid = user_id if user_id is not None else message.from_user.id
    lang = await get_user_lang(uid)
    services = await get_services(active_only=True)
    if not services:
        await message.answer(t("book_no_services", lang), parse_mode="HTML")
        return
    sent = await message.answer(
        t("book_category_prompt", lang),
        reply_markup=category_keyboard(lang),
        parse_mode="HTML",
    )
    _remember_services_msg(message.chat.id, sent.message_id)
    await state.set_state(BookingStates.choose_category)


async def _edit_to_category_picker(callback: CallbackQuery, state: FSMContext) -> None:
    """То же, но через edit_text — не плодит новые сообщения при навигации."""
    from utils.i18n import t
    from db import get_user_lang
    lang = await get_user_lang(callback.from_user.id)
    services = await get_services(active_only=True)
    if not services:
        try:
            await callback.message.edit_text(t("book_no_services", lang), parse_mode="HTML")
        except TelegramBadRequest:
            pass
        return
    _remember_services_msg(callback.message.chat.id, callback.message.message_id)
    try:
        await callback.message.edit_text(
            t("book_category_prompt", lang),
            reply_markup=category_keyboard(lang),
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
    from utils.i18n import t
    from db import get_user_lang
    lang = await get_user_lang(callback.from_user.id)
    masters = await get_active_masters()
    date_prompt = t("book_date_prompt", lang)
    if not masters:
        # мастера не заведены — пропускаем шаг, идём к датам без привязки к мастеру
        day_off_weekdays = await _day_off_weekdays()
        try:
            await callback.message.edit_text(
                f"{service_header}\n\n{date_prompt}",
                reply_markup=dates_keyboard(day_off_weekdays, lang),
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
                f"{service_header}\n\n{date_prompt}",
                reply_markup=dates_keyboard(day_off_weekdays, lang),
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
            f"{service_header}\n\n{t('book_master_prompt', lang)}",
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

    # Phase 3 v.4: если клиент в первый раз (нет заполненного профиля) —
    # показываем переключатель языка ДО приветствия. После выбора колбэк
    # `lang_set_*` сохранит lang в профиль и запустит обычный флоу.
    from db import get_user_lang
    profile = await get_client_profile(message.from_user.id)
    has_filled_profile = profile and (profile.get("name") or profile.get("phone"))
    if not has_filled_profile:
        from utils.i18n import t, Lang
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=t("lang_btn_ru"), callback_data="lang_set_ru"),
                InlineKeyboardButton(text=t("lang_btn_uz"), callback_data="lang_set_uz"),
            ],
        ])
        await message.answer(t("lang_picker_prompt"), reply_markup=kb, parse_mode="HTML")
        return

    # Уже знакомый клиент — берём его язык, показываем reply-клаву и идём дальше.
    lang = await get_user_lang(message.from_user.id)
    await message.answer("\u2063", reply_markup=client_reply_keyboard(lang))

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
            lang=lang,
        )
        await message.answer(greet, parse_mode="HTML")

        # Небольшая пауза перед меню — воздух между репликами
        await asyncio.sleep(0.6)

        svc_name_short = last_completed["service_name"][:45]
        repeat_text = f"{REPEAT}  takrorlash · {svc_name_short}" if lang == "uz" else f"{REPEAT}  повторить · {svc_name_short}"
        another_text = f"{ARROW_SOFT} boshqasini tanlash" if lang == "uz" else f"{ARROW_SOFT} выбрать другое"
        what_today_text = "<i>bugun nima?</i>" if lang == "uz" else "<i>что сегодня?</i>"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=repeat_text, callback_data=f"quick_rebook_{last_completed['id']}")],
            [InlineKeyboardButton(text=another_text, callback_data="client_restart")],
        ])
        await message.answer(
            f"{what_today_text}\n{DIVIDER_WHISPER}",
            reply_markup=kb,
            parse_mode="HTML",
        )
        await state.set_state(BookingStates.choose_service)
        return

    # Новый клиент — hero-приветствие + выбор категории (ручки/ножки)
    await message.answer(greeting_new(lang), parse_mode="HTML")
    await asyncio.sleep(0.5)
    await _send_category_picker(message, state)


# ─── BOOKING FLOW ────────────────────────────────────────────────────────────

@router.callback_query(BookingStates.choose_service, F.data.startswith("service_"))
async def choose_service(callback: CallbackQuery, state: FSMContext):
    from utils.i18n import t
    from db import get_user_lang
    lang = await get_user_lang(callback.from_user.id)
    parts = parse_callback(callback.data, "service", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    service_id = int(parts[0])
    service = await get_service_by_id(service_id)

    if service is None or not service["is_active"]:
        logger.warning("Unknown/inactive service_id=%s from user_id=%s", service_id, callback.from_user.id)
        await callback.answer(t("book_service_unavailable", lang), show_alert=True)
        await state.clear()
        return

    await state.update_data(
        service_id=service_id,
        service_name=service["name"],
        service_price=service["price"],
        service_duration=service["duration"],
        selected_addons=[],
    )

    dur_label = t("book_confirm_duration", lang)
    price_label = t("book_confirm_price", lang)
    desc = service.get("description")
    desc_line = f"\n\n<i>{h(desc)}</i>" if desc else ""
    service_card = (
        f"<blockquote>"
        f"<b><i>{h(service['name'].lower())}</i></b>"
        f"{desc_line}\n\n"
        f"{DIVIDER_SOFT}\n\n"
        f"<i>{dur_label}</i>   <code>{fmt_dur(service['duration'], lang)}</code>\n"
        f"<i>{price_label}</i>      <code>{fmt_price(service['price'], lang)}</code>"
        f"</blockquote>"
    )

    addons = await get_addons_for_service(service_id)
    if addons:
        try:
            await callback.message.edit_text(
                f"{service_card}\n\n{t('book_addons_prompt', lang)}",
                reply_markup=addons_keyboard(addons, lang=lang),
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
    from utils.i18n import t
    from db import get_user_lang
    lang = await get_user_lang(callback.from_user.id)
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
    dur_label = t("book_confirm_duration", lang)
    price_label = t("book_confirm_price", lang)
    try:
        total = calculate_total_price(data["service_price"], selected, addons)
        service_card = (
            f"<blockquote>"
            f"<b><i>{h(data['service_name'].lower())}</i></b>\n\n"
            f"{DIVIDER_SOFT}\n\n"
            f"<i>{dur_label}</i>   <code>{fmt_dur(data['service_duration'], lang)}</code>\n"
            f"<i>{price_label}</i>      <code>{fmt_price(total, lang)}</code>"
            f"</blockquote>"
        )
        await callback.message.edit_text(
            f"{service_card}\n\n{t('book_addons_prompt', lang)}",
            reply_markup=addons_keyboard(addons, set(selected), lang=lang),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(BookingStates.choose_addons, F.data == "addons_done")
async def cb_addons_done(callback: CallbackQuery, state: FSMContext):
    """Завершить выбор доп. опций — перейти к дате."""
    from utils.i18n import t
    from db import get_user_lang
    lang = await get_user_lang(callback.from_user.id)
    data = await state.get_data()
    selected: list[int] = data.get("selected_addons", [])

    addons = await get_addons_for_service(data["service_id"])
    final_price = calculate_total_price(data["service_price"], selected, addons)
    addon_names = addon_names_for(selected, addons)

    await state.update_data(
        service_price=final_price,
        addon_names=addon_names,
    )

    dur_label = t("book_confirm_duration", lang)
    price_label = t("book_confirm_price", lang)
    addon_line = (f"<i>+ {h(', '.join(addon_names).lower())}</i>\n\n") if addon_names else ""
    header = (
        f"<blockquote>"
        f"<b><i>{h(data['service_name'].lower())}</i></b>\n\n"
        f"{addon_line}"
        f"{DIVIDER_SOFT}\n\n"
        f"<i>{dur_label}</i>   <code>{fmt_dur(data['service_duration'], lang)}</code>\n"
        f"<i>{price_label}</i>      <code>{fmt_price(final_price, lang)}</code>"
        f"</blockquote>"
    )
    await _show_master_step(callback, state, header)


@router.callback_query(BookingStates.choose_master, F.data.startswith("master_"))
async def choose_master(callback: CallbackQuery, state: FSMContext):
    from utils.i18n import t
    from db import get_user_lang
    lang = await get_user_lang(callback.from_user.id)
    parts = parse_callback(callback.data, "master", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    master_id = int(parts[0])
    master = await get_master(master_id)
    if not master or not master["is_active"]:
        await callback.answer(t("book_master_unavailable", lang), show_alert=True)
        return

    await state.update_data(master_id=master_id, master_name=master["name"])
    data = await state.get_data()

    dur_label = t("book_confirm_duration", lang)
    price_label = t("book_confirm_price", lang)
    addon_line = (f"<i>+ {h(', '.join(data['addon_names']).lower())}</i>\n\n") if data.get("addon_names") else ""
    service_card = (
        f"<blockquote>"
        f"<b><i>{h(data['service_name'].lower())}</i></b>\n\n"
        f"{addon_line}"
        f"{DIVIDER_SOFT}\n\n"
        f"<i>{dur_label}</i>   <code>{fmt_dur(data['service_duration'], lang)}</code>\n"
        f"<i>{price_label}</i>      <code>{fmt_price(data['service_price'], lang)}</code>"
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
            f"{t('book_date_prompt', lang)}",
            reply_markup=dates_keyboard(day_off_weekdays, lang),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await state.set_state(BookingStates.choose_date)
    await callback.answer()


@router.callback_query(BookingStates.choose_date, F.data.startswith("date_"))
async def choose_date(callback: CallbackQuery, state: FSMContext):
    from utils.i18n import t
    from db import get_user_lang
    lang = await get_user_lang(callback.from_user.id)
    parts = parse_callback(callback.data, "date", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    date_str = parts[0]
    data = await state.get_data()
    duration = data["service_duration"]
    master_id: int | None = data.get("master_id")

    if master_id is not None:
        day_off_weekdays = await get_day_off_weekdays_for_master(master_id)
    else:
        day_off_weekdays = await _day_off_weekdays()

    ctx, free_slots = await compute_free_slots(master_id, date_str, duration)

    if ctx.is_day_off or not free_slots:
        try:
            await callback.message.edit_text(
                t("book_no_free_slots", lang),
                reply_markup=dates_keyboard(day_off_weekdays, lang),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
        await callback.answer()
        return

    await state.update_data(date=date_str)
    try:
        await callback.message.edit_text(
            f"<b><i>{date_soft(date_str, lang)}</i></b>\n\n"
            f"{t('book_time_prompt', lang)}",
            reply_markup=times_keyboard(free_slots),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await state.set_state(BookingStates.choose_time)
    await callback.answer()


@router.callback_query(BookingStates.choose_time, F.data.startswith("time_"))
async def choose_time(callback: CallbackQuery, state: FSMContext):
    from utils.i18n import t
    from db import get_user_lang
    lang = await get_user_lang(callback.from_user.id)
    parts = parse_callback(callback.data, "time", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    time_str = parts[0]
    await state.update_data(time=time_str)

    profile = await get_client_profile(callback.from_user.id)
    has_filled_profile = profile and (profile.get("name") or profile.get("phone"))
    if has_filled_profile:
        try:
            await callback.message.edit_text(
                f"{t('book_profile_saved_question', lang)}\n"
                f"{DIVIDER_WHISPER}\n\n"
                f"<b>{profile['name']}</b>  ·  <code>{profile['phone']}</code>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=t("book_profile_use_saved", lang), callback_data="use_saved_profile")],
                    [InlineKeyboardButton(text=t("book_profile_new", lang), callback_data="change_profile")],
                ]),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
        await state.set_state(BookingStates.confirm_profile)
    else:
        try:
            await callback.message.edit_text(
                t("book_ask_name", lang),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
        await state.set_state(BookingStates.get_name)
    await callback.answer()


def _render_summary(data: dict, lang: str) -> str:
    """Сводка записи перед confirm_yes. Используется и при use_saved_profile,
    и при get_phone — чтобы одна и та же версия текста была в обоих местах."""
    from utils.i18n import t
    when_label = t("book_confirm_when", lang)
    price_label = t("book_confirm_price", lang)
    master_label = t("book_confirm_master", lang)
    header = t("book_confirm_header", lang)
    addon_line = (f"\n<i>+ {h(', '.join(data['addon_names']).lower())}</i>") if data.get("addon_names") else ""
    master_line = (f"\n<i>{master_label} · {h(data['master_name'].title())}</i>") if data.get("master_name") else ""
    return (
        f"<blockquote>"
        f"{header}\n\n"
        f"{DIVIDER_SOFT}\n\n"
        f"<b>{h(data['service_name'].lower())}</b>"
        f"{addon_line}"
        f"{master_line}\n\n"
        f"<i>{when_label}</i>       <code>{date_soft(data['date'], lang)} · {data['time']}</code>\n"
        f"<i>{price_label}</i>   <code>{fmt_price(data['service_price'], lang)}</code>\n\n"
        f"<i>{h(data['name'])} · {h(data['phone'])}</i>"
        f"</blockquote>"
    )


@router.callback_query(BookingStates.confirm_profile, F.data == "use_saved_profile")
async def use_saved_profile(callback: CallbackQuery, state: FSMContext):
    from utils.i18n import t
    from db import get_user_lang
    lang = await get_user_lang(callback.from_user.id)
    profile = await get_client_profile(callback.from_user.id)
    if not profile:
        try:
            await callback.message.edit_text(t("book_ask_name", lang), parse_mode="HTML")
        except TelegramBadRequest:
            pass
        await state.set_state(BookingStates.get_name)
        await callback.answer()
        return

    await state.update_data(name=profile["name"], phone=profile["phone"])
    data = await state.get_data()
    try:
        await callback.message.edit_text(
            _render_summary(data, lang),
            reply_markup=confirm_keyboard(lang),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await state.set_state(BookingStates.confirm)
    await callback.answer()


@router.callback_query(BookingStates.confirm_profile, F.data == "change_profile")
async def change_profile(callback: CallbackQuery, state: FSMContext):
    from utils.i18n import t
    from db import get_user_lang
    lang = await get_user_lang(callback.from_user.id)
    try:
        await callback.message.edit_text(t("book_ask_name", lang), parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await state.set_state(BookingStates.get_name)
    await callback.answer()


_RESERVED_NAMES = frozenset({"записаться", "мои записи"})


_RESERVED_NAMES_UZ = frozenset({
    "yozilish", "mening yozilishlarim",
    "Yozilish".lower(), "Mening yozuvlarim".lower(),
})


@router.message(BookingStates.get_name)
async def get_name(message: Message, state: FSMContext):
    from utils.i18n import t
    from db import get_user_lang
    lang = await get_user_lang(message.from_user.id)
    name = message.text.strip() if message.text else ""
    if (not name or len(name) < 2 or len(name) > 64
            or name.lower() in _RESERVED_NAMES or name.lower() in _RESERVED_NAMES_UZ
            or name.startswith("/")):
        await message.answer(t("book_name_too_short", lang), parse_mode="HTML")
        return
    await state.update_data(name=name)
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    phone_prompt = await message.answer(
        t("book_ask_phone", lang),
        reply_markup=contact_keyboard(lang),
        parse_mode="HTML",
    )
    await state.update_data(_phone_prompt_msg_id=phone_prompt.message_id)
    await state.set_state(BookingStates.get_phone)


@router.message(BookingStates.get_phone, F.contact)
async def get_phone(message: Message, state: FSMContext):
    from utils.i18n import t
    from db import get_user_lang
    lang = await get_user_lang(message.from_user.id)
    contact = message.contact
    if contact.user_id is None or contact.user_id != message.from_user.id:
        await message.answer(
            t("book_ask_phone", lang),
            reply_markup=contact_keyboard(lang),
            parse_mode="HTML",
        )
        return
    phone = contact.phone_number
    await state.update_data(phone=phone)

    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    data = await state.get_data()
    summary = _render_summary(data, lang)
    summary_msg = await message.answer(
        summary,
        reply_markup=client_reply_keyboard(lang),
        parse_mode="HTML",
    )
    await state.update_data(_summary_msg_id=summary_msg.message_id)

    await message.answer(
        t("book_confirm_header", lang),
        reply_markup=confirm_keyboard(lang),
        parse_mode="HTML",
    )
    await state.set_state(BookingStates.confirm)


@router.callback_query(BookingStates.confirm, F.data == "confirm_yes")
async def confirm_yes(callback: CallbackQuery, state: FSMContext):
    from utils.i18n import t
    from db import get_user_lang
    lang = await get_user_lang(callback.from_user.id)
    data = await state.get_data()
    master_id: int | None = data.get("master_id")

    # Финальная проверка мастера: между выбором и подтверждением админ мог
    # деактивировать/удалить мастера. Запись к «призраку» не создаём.
    if master_id is not None and await resolve_active_master(master_id) is None:
        try:
            await callback.message.edit_text(
                t("book_master_unavailable", lang),
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
                t("book_slot_taken", lang),
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
                t("book_generic_error", lang),
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

    # Ранний ack — чтобы у клиента не висел «часики» на inline-кнопке пока
    # мы долбимся в create_invoice (Click/Payme API timeout = 10s).
    # Запись уже создана, FSM очищен — бэкофис может занимать сколько хочет.
    try:
        await callback.answer()
    except Exception:
        pass

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
        # Не называем переменную `t`: выше импортирован i18n-хелпер t(key, lang),
        # который нужен ниже в confirm_yes (master_label, price_label и т.д.).
        bg_task = asyncio.create_task(coro)
        _bg_tasks.add(bg_task)
        bg_task.add_done_callback(_bg_tasks.discard)

    addon_line_done = (f"\n<i>+ {h(', '.join(data.get('addon_names', [])).lower())}</i>") if data.get("addon_names") else ""
    master_label = t("book_confirm_master", lang)
    master_line_done = (f"\n<i>{master_label} · {h(data['master_name'].title())}</i>") if data.get("master_name") else ""
    when_label = t("book_confirm_when", lang)
    dur_label = t("book_confirm_duration", lang)
    price_label = "to'lovga" if lang == "uz" else "к оплате"
    wait_line = f"{h(data['name'])}, kutaman." if lang == "uz" else f"{h(data['name'])}, жду тебя."

    # 1. Hero — АКЦЕНТ на успехе сразу же. Без await delete_message перед ним:
    # три sequential delete_message давали 500-800мс задержки до первого
    # сообщения клиенту.
    try:
        await callback.message.edit_text(
            booking_done_hero(data['name'], lang),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass

    # 2. Детальная карточка в blockquote.
    await callback.message.answer(
        f"<blockquote>"
        f"<b><i>{wait_line}</i></b>\n\n"
        f"{DIVIDER_SOFT}\n\n"
        f"<b>{h(data['service_name'].lower())}</b>"
        f"{addon_line_done}"
        f"{master_line_done}\n\n"
        f"<i>{when_label}</i>         <code>{date_soft(data['date'], lang)} · {data['time']}</code>\n"
        f"<i>{dur_label}</i>  <code>{fmt_dur(data['service_duration'], lang)}</code>\n"
        f"<i>{price_label}</i>      <code>{fmt_price(data['service_price'], lang)}</code>"
        f"</blockquote>",
        parse_mode="HTML",
    )

    # 3. Мягкое напоминание.
    await callback.message.answer(
        booking_reminder_note(lang),
        reply_markup=client_reply_keyboard(lang),
        parse_mode="HTML",
    )

    # 4. Уборка transient-сообщений флоу — в фон. Клиенту не критично, чтобы
    # они исчезли мгновенно; hero+blockquote+reminder уже на экране.
    flow_msg_id = _client_services_msg.pop(callback.message.chat.id, None)
    transient_ids = [
        mid for mid in (flow_msg_id, data.get("_phone_prompt_msg_id"), data.get("_summary_msg_id"))
        if mid and mid != callback.message.message_id
    ]
    if transient_ids:
        chat_id = callback.message.chat.id
        bot_ref = callback.bot

        async def _bg_delete_transient() -> None:
            for mid in transient_ids:
                try:
                    await bot_ref.delete_message(chat_id, mid)
                except TelegramBadRequest:
                    pass

        _del_task = asyncio.create_task(_bg_delete_transient())
        _bg_tasks.add(_del_task)
        _del_task.add_done_callback(_bg_tasks.discard)

    # 5. Ссылка на оплату — в фон: create_invoice делает HTTP-запрос к Click/
    # Payme API (таймаут 10 сек), не должен задерживать показ booking-confirm.
    # Если провайдер ответил — шлём отдельное сообщение с кнопкой «Оплатить».
    from keyboards.inline import payment_keyboard
    from utils.payments import get_provider
    from config import PAYMENT_URL, PAYMENT_LABEL

    async def _bg_send_pay_link() -> None:
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
                logger.exception("create_invoice failed for appt=%s", appt_id)

        # Fallback на legacy PAYMENT_URL — если провайдер не сработал
        # (упал / не настроен), но оператор задал запасную ссылку в .env.
        if pay_url is None and PAYMENT_URL:
            pay_url = (
                PAYMENT_URL
                .replace("{amount}", str(data["service_price"]))
                .replace("{appt_id}", str(appt_id))
            )

        pay_kb = payment_keyboard(pay_url, label=t("pay_btn", lang))
        if pay_kb:
            try:
                await callback.message.answer(
                    t("pay_link_text", lang),
                    reply_markup=pay_kb,
                    parse_mode="HTML",
                )
            except Exception:
                logger.exception("не смог доставить ссылку на оплату appt=%s", appt_id)
        else:
            logger.warning(
                "pay link не показан: provider=%s pay_url=%s legacy=%s",
                (provider.name if provider else None), pay_url, bool(PAYMENT_URL),
            )

    _pay_task = asyncio.create_task(_bg_send_pay_link())
    _bg_tasks.add(_pay_task)
    _pay_task.add_done_callback(_bg_tasks.discard)


@router.callback_query(BookingStates.confirm, F.data == "confirm_no")
async def confirm_no(callback: CallbackQuery, state: FSMContext):
    from utils.i18n import t
    from db import get_user_lang
    lang = await get_user_lang(callback.from_user.id)
    await state.clear()
    back_text = "yaxshi. yozilish bekor." if lang == "uz" else "хорошо. ничего не создаём."
    back_btn = "← xizmatlarga" if lang == "uz" else "← к услугам"
    try:
        await callback.message.edit_text(
            f"<i>{back_text}</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=back_btn, callback_data="client_restart"),
            ]]),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.message(BookingStates.get_phone)
async def get_phone_wrong(message: Message):
    from utils.i18n import t
    from db import get_user_lang
    lang = await get_user_lang(message.from_user.id)
    await message.answer(
        t("book_ask_phone", lang),
        reply_markup=contact_keyboard(lang),
        parse_mode="HTML",
    )


@router.message(BookingStates.confirm, F.text.in_({"записаться", "yozilish", "Yozilish", "/start"}))
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
    from db import get_user_lang
    lang = await get_user_lang(message.from_user.id)
    text = "<i>yuqoridagi tugmalardan foydalaning.</i>" if lang == "uz" else "<i>используй кнопки выше.</i>"
    await message.answer(text, parse_mode="HTML")


@router.callback_query(F.data == "client_restart")
async def cb_client_restart(callback: CallbackQuery, state: FSMContext):
    """«выбрать другое» у возвращающегося клиента → обратно к выбору категории."""
    await state.clear()
    await _edit_to_category_picker(callback, state)
    await callback.answer()


@router.callback_query(F.data.in_({"cat_hands", "cat_feet"}))
async def cb_pick_category(callback: CallbackQuery, state: FSMContext):
    """Клиент выбрал категорию — показываем услуги в ней с ценами."""
    from utils.i18n import t
    from db import get_user_lang
    lang = await get_user_lang(callback.from_user.id)
    category = "hands" if callback.data == "cat_hands" else "feet"
    services = await get_services(active_only=True, category=category)
    if not services:
        empty_hint = "<i>tanlangan kategoriyada hozircha xizmatlar yo'q. boshqasini tanlang:</i>" if lang == "uz" else "<i>тут пока пусто. попробуй другую:</i>"
        try:
            await callback.message.edit_text(
                f"{empty_hint}\n\n{t('book_category_prompt', lang)}",
                reply_markup=category_keyboard(lang),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
        await callback.answer()
        return
    _remember_services_msg(callback.message.chat.id, callback.message.message_id)
    try:
        await callback.message.edit_text(
            t("book_services_prompt", lang),
            reply_markup=services_keyboard(services, with_back=True, lang=lang),
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


@router.message(F.text.in_({"записаться", "yozilish", "Yozilish"}))
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


# ─── ПЕРЕКЛЮЧАТЕЛЬ ЯЗЫКА (Phase 3 v.4) ──────────────────────────────────────

@router.callback_query(F.data.in_({"lang_set_ru", "lang_set_uz"}))
async def cb_lang_set(callback: CallbackQuery, state: FSMContext):
    """Сохранить выбор языка клиента + запустить обычный /start-флоу."""
    from db import set_user_lang, get_client_profile, get_client_appointments
    from utils.i18n import t, Lang
    lang = Lang.UZ if callback.data == "lang_set_uz" else Lang.RU
    await set_user_lang(callback.from_user.id, lang)

    # Подтверждение + reply-клава на выбранном языке.
    try:
        await callback.message.edit_text(t("lang_changed", lang), parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()

    await callback.message.answer(
        "\u2063", reply_markup=client_reply_keyboard(lang)
    )
    await asyncio.sleep(0.3)

    # Продолжение обычного /start для нового клиента — hero + категории.
    # Полный текст приветствия пока на ru (будет переведён в чекпоинте 2).
    profile = await get_client_profile(callback.from_user.id)
    last_appts = await get_client_appointments(callback.from_user.id) if profile else []
    last_completed = next((a for a in last_appts if a["status"] == "completed"), None)
    if profile and last_completed:
        # Возвращающийся клиент — не должен был сюда попасть, но safety.
        return

    await callback.message.answer(greeting_new(lang), parse_mode="HTML")
    await asyncio.sleep(0.4)
    await _send_category_picker(callback.message, state, user_id=callback.from_user.id)


@router.callback_query(F.data == "lang_picker")
async def cb_lang_picker(callback: CallbackQuery, state: FSMContext):
    """Открыть переключатель языка из «мои записи»."""
    await state.clear()
    from utils.i18n import t
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t("lang_btn_ru"), callback_data="lang_set_ru"),
            InlineKeyboardButton(text=t("lang_btn_uz"), callback_data="lang_set_uz"),
        ],
    ])
    try:
        await callback.message.edit_text(
            t("lang_picker_prompt"), reply_markup=kb, parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.message(F.text.regexp(r"^/(language|til|lang)(?:\s|$)") | (F.text == "🌐 Язык / Til"))
async def cmd_change_lang(message: Message, state: FSMContext):
    """Клиент сменяет язык через команду /language (или /til, /lang)."""
    await state.clear()
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    from utils.i18n import t
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t("lang_btn_ru"), callback_data="lang_set_ru"),
            InlineKeyboardButton(text=t("lang_btn_uz"), callback_data="lang_set_uz"),
        ],
    ])
    await message.answer(t("lang_picker_prompt"), reply_markup=kb, parse_mode="HTML")


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
