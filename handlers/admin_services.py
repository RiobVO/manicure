import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from states import AdminStates
from db import (
    get_services, get_service_by_id,
    update_service_name, update_service_price, update_service_duration,
    update_service_description,
    toggle_service_active, delete_service, add_service,
    service_has_future_appointments, log_admin_action, _price_fmt,
    get_addons_for_service, get_addon_by_id, add_addon,
    delete_addon, toggle_addon_active,
)
from keyboards.inline import (
    services_list_keyboard, service_detail_keyboard, admin_cancel_keyboard,
    addon_manage_keyboard, addon_detail_keyboard,
    admin_category_picker,
)
from utils.admin import is_admin_callback, is_admin_message, deny_access, IsAdminFilter
from utils.callbacks import parse_callback
from utils.panel import edit_panel, edit_panel_with_callback

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(IsAdminFilter())
router.callback_query.filter(IsAdminFilter())


def _service_text(service: dict) -> str:
    status = "🟢 Активна" if service["is_active"] else "🔴 Неактивна"
    desc = f"\n📝 {service['description']}" if service.get("description") else ""
    return (
        f"💅 {service['name']}\n\n"
        f"💰 Цена: {_price_fmt(service['price'])} сум\n"
        f"⏱ Длительность: {service['duration']} мин\n"
        f"📌 Статус: {status}"
        f"{desc}"
    )


async def _show_services(callback: CallbackQuery):
    services = await get_services(active_only=False)
    await edit_panel_with_callback(callback, "💅 Управление услугами:", services_list_keyboard(services))


async def _show_service_detail(callback: CallbackQuery, service_id: int):
    service = await get_service_by_id(service_id)
    if not service:
        await callback.answer("Услуга не найдена.", show_alert=True)
        return
    await edit_panel_with_callback(callback, _service_text(service), service_detail_keyboard(service))


@router.callback_query(F.data == "admin_services")
async def cb_admin_services(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    await _show_services(callback)


@router.callback_query(F.data.startswith("svc_detail_"))
async def cb_svc_detail(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "svc_detail", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    service_id = int(parts[0])
    await _show_service_detail(callback, service_id)


@router.callback_query(F.data.startswith("svc_toggle_"))
async def cb_svc_toggle(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "svc_toggle", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    service_id = int(parts[0])
    service = await get_service_by_id(service_id)
    await toggle_service_active(service_id)

    if service:
        action = "activate" if not service["is_active"] else "deactivate"
        await log_admin_action(
            admin_id=callback.from_user.id,
            action=action,
            target_type="service",
            target_id=service_id,
            details=service["name"],
        )

    await _show_service_detail(callback, service_id)


@router.callback_query(F.data.startswith("svc_delete_"))
async def cb_svc_delete(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "svc_delete", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    service_id = int(parts[0])

    if await service_has_future_appointments(service_id):
        await callback.answer(
            "Нельзя удалить: есть будущие записи на эту услугу.",
            show_alert=True
        )
        return

    service = await get_service_by_id(service_id)
    await delete_service(service_id)

    if service:
        await log_admin_action(
            admin_id=callback.from_user.id,
            action="delete_service",
            target_type="service",
            target_id=service_id,
            details=service["name"],
        )

    await _show_services(callback)


# ─── РЕДАКТИРОВАНИЕ НАЗВАНИЯ ─────────────────────────────────────────────────

@router.callback_query(F.data.startswith("svc_edit_name_"))
async def cb_svc_edit_name(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "svc_edit_name", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    service_id = int(parts[0])
    await state.update_data(editing_service_id=service_id)
    await edit_panel_with_callback(callback, "✏️ Введите новое название услуги:", admin_cancel_keyboard())
    await state.set_state(AdminStates.service_edit_name)
    await callback.answer()


@router.message(AdminStates.service_edit_name)
async def msg_svc_edit_name(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass
    name = message.text.strip() if message.text else ""
    if not name or len(name) > 100:
        await edit_panel(message.bot, message.chat.id, "⚠️ Введите название (не более 100 символов):", admin_cancel_keyboard())
        return
    data = await state.get_data()
    service_id = data["editing_service_id"]

    old_service = await get_service_by_id(service_id)
    await update_service_name(service_id, name)
    await log_admin_action(
        admin_id=message.from_user.id,
        action="edit_service_name",
        target_type="service",
        target_id=service_id,
        details=f"{old_service['name'] if old_service else '?'} → {name}",
    )

    await state.clear()
    service = await get_service_by_id(service_id)
    await edit_panel(message.bot, message.chat.id, _service_text(service), service_detail_keyboard(service))


# ─── РЕДАКТИРОВАНИЕ ЦЕНЫ ─────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("svc_edit_price_"))
async def cb_svc_edit_price(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "svc_edit_price", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    service_id = int(parts[0])
    await state.update_data(editing_service_id=service_id)
    await edit_panel_with_callback(callback, "💰 Введите новую цену (целое число, сум):", admin_cancel_keyboard())
    await state.set_state(AdminStates.service_edit_price)
    await callback.answer()


@router.message(AdminStates.service_edit_price)
async def msg_svc_edit_price(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass
    try:
        price = int(message.text.strip())
        if price <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        await edit_panel(message.bot, message.chat.id, "⚠️ Введите корректную цену (целое положительное число):", admin_cancel_keyboard())
        return
    data = await state.get_data()
    service_id = data["editing_service_id"]

    old_service = await get_service_by_id(service_id)
    await update_service_price(service_id, price)
    await log_admin_action(
        admin_id=message.from_user.id,
        action="edit_service_price",
        target_type="service",
        target_id=service_id,
        details=f"{old_service['price'] if old_service else '?'} → {price} сум",
    )

    await state.clear()
    service = await get_service_by_id(service_id)
    await edit_panel(message.bot, message.chat.id, _service_text(service), service_detail_keyboard(service))


# ─── РЕДАКТИРОВАНИЕ ДЛИТЕЛЬНОСТИ ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("svc_edit_dur_"))
async def cb_svc_edit_dur(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "svc_edit_dur", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    service_id = int(parts[0])
    await state.update_data(editing_service_id=service_id)
    await edit_panel_with_callback(callback, "⏱ Введите новую длительность (минуты, от 5 до 480):", admin_cancel_keyboard())
    await state.set_state(AdminStates.service_edit_duration)
    await callback.answer()


@router.message(AdminStates.service_edit_duration)
async def msg_svc_edit_dur(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass
    try:
        duration = int(message.text.strip())
        if not (5 <= duration <= 480):
            raise ValueError
    except (ValueError, AttributeError):
        await edit_panel(message.bot, message.chat.id, "⚠️ Введите длительность от 5 до 480 минут:", admin_cancel_keyboard())
        return
    data = await state.get_data()
    service_id = data["editing_service_id"]
    await update_service_duration(service_id, duration)
    await state.clear()
    service = await get_service_by_id(service_id)
    await edit_panel(message.bot, message.chat.id, _service_text(service), service_detail_keyboard(service))


# ─── РЕДАКТИРОВАНИЕ ОПИСАНИЯ ─────────────────────────────────────────────────

@router.callback_query(F.data.startswith("svc_edit_desc_"))
async def cb_svc_edit_desc(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "svc_edit_desc", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    service_id = int(parts[0])
    await state.update_data(editing_service_id=service_id)
    await edit_panel_with_callback(
        callback,
        "📝 Введите описание услуги (или 'нет' чтобы убрать):\n\n"
        "Например: 'Покрытие гель-лаком с дизайном, до 4-х ногтей бесплатно'",
        admin_cancel_keyboard()
    )
    await state.set_state(AdminStates.service_edit_description)
    await callback.answer()


@router.message(AdminStates.service_edit_description)
async def msg_svc_edit_desc_save(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass

    description = message.text.strip() if message.text else ""
    if description.lower() in ("нет", "-", "убрать", ""):
        description = ""

    data = await state.get_data()
    service_id = data.get("editing_service_id")
    if service_id:
        await update_service_description(service_id, description)
        await log_admin_action(
            admin_id=message.from_user.id,
            action="edit_service_desc",
            target_type="service",
            target_id=service_id,
            details="Описание обновлено",
        )
        await state.clear()
        service = await get_service_by_id(service_id)
        await edit_panel(message.bot, message.chat.id, _service_text(service), service_detail_keyboard(service))



# ─── ДОБАВЛЕНИЕ УСЛУГИ ───────────────────────────────────────────────────────

@router.callback_query(F.data == "svc_add")
async def cb_svc_add(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    await edit_panel_with_callback(callback, "➕ Введите название новой услуги:", admin_cancel_keyboard())
    await state.set_state(AdminStates.service_add_name)
    await callback.answer()


@router.message(AdminStates.service_add_name)
async def msg_svc_add_name(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass
    name = message.text.strip() if message.text else ""
    if not name or len(name) > 100:
        await edit_panel(message.bot, message.chat.id, "⚠️ Введите название (не более 100 символов):", admin_cancel_keyboard())
        return
    await state.update_data(new_service_name=name)
    await edit_panel(message.bot, message.chat.id, "💰 Введите цену (целое число, сум):", admin_cancel_keyboard())
    await state.set_state(AdminStates.service_add_price)


@router.message(AdminStates.service_add_price)
async def msg_svc_add_price(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass
    try:
        price = int(message.text.strip())
        if price <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        await edit_panel(message.bot, message.chat.id, "⚠️ Введите корректную цену:", admin_cancel_keyboard())
        return
    await state.update_data(new_service_price=price)
    await edit_panel(message.bot, message.chat.id, "⏱ Введите длительность (минуты, от 5 до 480):", admin_cancel_keyboard())
    await state.set_state(AdminStates.service_add_duration)


@router.message(AdminStates.service_add_duration)
async def msg_svc_add_dur(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass
    try:
        duration = int(message.text.strip())
        if not (5 <= duration <= 480):
            raise ValueError
    except (ValueError, AttributeError):
        await edit_panel(message.bot, message.chat.id, "⚠️ Введите длительность от 5 до 480 минут:", admin_cancel_keyboard())
        return

    await state.update_data(new_service_duration=duration)
    await edit_panel(
        message.bot, message.chat.id,
        "🗂 К какой категории относится услуга?",
        admin_category_picker(),
    )
    await state.set_state(AdminStates.service_add_category)


@router.callback_query(
    AdminStates.service_add_category,
    F.data.in_({"svc_cat_hands", "svc_cat_feet"}),
)
async def cb_svc_add_category(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    category = "hands" if callback.data == "svc_cat_hands" else "feet"
    data = await state.get_data()

    service_id = await add_service(
        data["new_service_name"],
        data["new_service_price"],
        data["new_service_duration"],
        category=category,
    )

    await log_admin_action(
        admin_id=callback.from_user.id,
        action="add_service",
        target_type="service",
        target_id=service_id,
        details=(
            f"{data['new_service_name']} — {data['new_service_price']} сум, "
            f"{data['new_service_duration']} мин, {category}"
        ),
    )

    await state.clear()

    services = await get_services(active_only=False)
    await edit_panel_with_callback(
        callback,
        f"✅ Услуга добавлена: {data['new_service_name']}\n\n💅 Управление услугами:",
        services_list_keyboard(services),
    )
    await callback.answer()


# ─── УПРАВЛЕНИЕ ДОП. ОПЦИЯМИ (АДДОНЫ) ──────────────────────────────────────

@router.callback_query(F.data.startswith("svc_addons_"))
async def cb_svc_addons(callback: CallbackQuery):
    """Список доп. опций услуги."""
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "svc_addons", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    service_id = int(parts[0])
    service = await get_service_by_id(service_id)
    if not service:
        await callback.answer("Услуга не найдена.", show_alert=True)
        return
    addons = await get_addons_for_service(service_id, active_only=False)
    await edit_panel_with_callback(
        callback,
        f"✨ <b>Доп. опции: {service['name']}</b>\n\n"
        + (("\n".join(
            f"{'🟢' if a['is_active'] else '🔴'} {a['name']} — {_price_fmt(a['price'])} сум"
            for a in addons
        )) if addons else "Нет опций"),
        addon_manage_keyboard(addons, service_id),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("addon_detail_"))
async def cb_addon_detail(callback: CallbackQuery):
    """Детали аддона — переключить/удалить."""
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "addon_detail", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    addon_id = int(parts[0])
    addon = await get_addon_by_id(addon_id)
    if not addon:
        await callback.answer("Опция не найдена.", show_alert=True)
        return
    status = "🟢 Активна" if addon["is_active"] else "🔴 Неактивна"
    await edit_panel_with_callback(
        callback,
        f"✨ <b>{addon['name']}</b>\n\n"
        f"💰 Цена: {_price_fmt(addon['price'])} сум\n"
        f"📌 Статус: {status}",
        addon_detail_keyboard(addon),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("addon_toggle_"))
async def cb_addon_toggle(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "addon_toggle", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    addon_id = int(parts[0])
    await toggle_addon_active(addon_id)
    addon = await get_addon_by_id(addon_id)
    if not addon:
        await callback.answer("Опция не найдена.", show_alert=True)
        return
    await log_admin_action(
        admin_id=callback.from_user.id,
        action="toggle_addon",
        target_type="addon",
        target_id=addon_id,
        details=addon["name"],
    )
    # Вернуться к списку аддонов
    addons = await get_addons_for_service(addon["service_id"], active_only=False)
    service = await get_service_by_id(addon["service_id"])
    await edit_panel_with_callback(
        callback,
        f"✨ <b>Доп. опции: {service['name']}</b>\n\n"
        + (("\n".join(
            f"{'🟢' if a['is_active'] else '🔴'} {a['name']} — {_price_fmt(a['price'])} сум"
            for a in addons
        )) if addons else "Нет опций"),
        addon_manage_keyboard(addons, addon["service_id"]),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("addon_delete_"))
async def cb_addon_delete(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "addon_delete", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    addon_id = int(parts[0])
    addon = await get_addon_by_id(addon_id)
    if not addon:
        await callback.answer("Опция не найдена.", show_alert=True)
        return
    service_id = addon["service_id"]
    await delete_addon(addon_id)
    await log_admin_action(
        admin_id=callback.from_user.id,
        action="delete_addon",
        target_type="addon",
        target_id=addon_id,
        details=addon["name"],
    )
    addons = await get_addons_for_service(service_id, active_only=False)
    service = await get_service_by_id(service_id)
    await edit_panel_with_callback(
        callback,
        f"✨ <b>Доп. опции: {service['name']}</b>\n\n"
        + (("\n".join(
            f"{'🟢' if a['is_active'] else '🔴'} {a['name']} — {_price_fmt(a['price'])} сум"
            for a in addons
        )) if addons else "Нет опций"),
        addon_manage_keyboard(addons, service_id),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("addon_add_"))
async def cb_addon_add(callback: CallbackQuery, state: FSMContext):
    """Начать добавление новой доп. опции."""
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "addon_add", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    service_id = int(parts[0])
    await state.update_data(addon_service_id=service_id)
    await edit_panel_with_callback(
        callback,
        "✨ Введите название доп. опции:",
        admin_cancel_keyboard(),
    )
    await state.set_state(AdminStates.addon_add_name)
    await callback.answer()


@router.message(AdminStates.addon_add_name)
async def msg_addon_add_name(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass
    name = message.text.strip() if message.text else ""
    if not name or len(name) > 100:
        await edit_panel(message.bot, message.chat.id, "⚠️ Введите название (не более 100 символов):", admin_cancel_keyboard())
        return
    await state.update_data(addon_name=name)
    await edit_panel(message.bot, message.chat.id, "💰 Введите цену доп. опции (целое число, сум):", admin_cancel_keyboard())
    await state.set_state(AdminStates.addon_add_price)


@router.message(AdminStates.addon_add_price)
async def msg_addon_add_price(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass
    try:
        price = int(message.text.strip())
        if price <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        await edit_panel(message.bot, message.chat.id, "⚠️ Введите корректную цену:", admin_cancel_keyboard())
        return

    data = await state.get_data()
    service_id = data["addon_service_id"]
    addon_id = await add_addon(service_id, data["addon_name"], price)

    await log_admin_action(
        admin_id=message.from_user.id,
        action="add_addon",
        target_type="addon",
        target_id=addon_id,
        details=f"{data['addon_name']} — {price} сум (service_id={service_id})",
    )

    await state.clear()

    addons = await get_addons_for_service(service_id, active_only=False)
    service = await get_service_by_id(service_id)
    await edit_panel(
        message.bot, message.chat.id,
        f"✅ Опция добавлена: {data['addon_name']}\n\n"
        f"✨ <b>Доп. опции: {service['name']}</b>\n\n"
        + (("\n".join(
            f"{'🟢' if a['is_active'] else '🔴'} {a['name']} — {_price_fmt(a['price'])} сум"
            for a in addons
        )) if addons else "Нет опций"),
        addon_manage_keyboard(addons, service_id),
        parse_mode="HTML",
    )
