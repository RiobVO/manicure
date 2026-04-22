"""
Админская панель «📈 Откуда клиенты» — управление источниками трафика
и QR-генератор для offline-лидов (Phase 2 v.4).

UX:
    reply «📈 Откуда клиенты» → список источников со статистикой + «➕ добавить»
    На каждом source: «📱 QR», «🗑 удалить».
    «📱 QR» → бот шлёт PNG-картинку + текст со ссылкой для публикации
             (Instagram, Telegram channel).
    «➕ добавить» → FSM: код (англ), затем label (подпись).

Источники desk/mirror/door засеяны на миграции v4→v5 — админу ничего
не надо настраивать, чтобы распечатать три QR в день установки.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from db.helpers import _price_fmt
from db.traffic import (
    aggregate_by_source,
    create_source,
    delete_source,
    get_source_by_id,
    list_sources,
    normalize_code,
)
from keyboards.inline import admin_cancel_keyboard
from states import AdminStates
from utils.admin import IsAdminFilter
from utils.panel import delete_in_bg, edit_panel, edit_panel_with_callback
from utils.qrgen import generate_qr

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(IsAdminFilter())
router.callback_query.filter(IsAdminFilter())


async def _bot_username(bot) -> str:
    """Кэшируем username бота на процесс — не зовём get_me() на каждый QR."""
    cached = getattr(bot, "_cached_username", None)
    if cached:
        return cached
    me = await bot.get_me()
    bot._cached_username = me.username  # type: ignore[attr-defined]
    return me.username


def _deep_link(username: str, code: str) -> str:
    return f"https://t.me/{username}?start={code}"


def _sources_keyboard(rows: list[dict]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for r in rows:
        buttons.append([InlineKeyboardButton(
            text=f"📱 {r['label']} · {r['code']}",
            callback_data=f"traffic_src_{r['id']}",
        )])
    buttons.append([InlineKeyboardButton(
        text="➕ добавить источник",
        callback_data="traffic_add",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _source_detail_keyboard(source_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 QR для печати", callback_data=f"traffic_qr_{source_id}")],
        [InlineKeyboardButton(text="🗑 удалить", callback_data=f"traffic_del_{source_id}")],
        [InlineKeyboardButton(text="🔙 к списку", callback_data="traffic_list")],
    ])


def _render_sources_text(stats: list[dict]) -> str:
    """Список источников + агрегаты одним сообщением."""
    if not stats:
        return "📈 <b>Откуда клиенты</b>\n\nПока нет источников."

    lines = ["📈 <b>Откуда клиенты</b>\n"]
    for r in stats:
        revenue = _price_fmt(int(r["revenue"])) if r["revenue"] else "—"
        lines.append(
            f"<b>{r['label']}</b> · <code>{r['code']}</code>\n"
            f"  клиенты: <b>{r['clients_count']}</b>"
            f" · записи: <b>{r['bookings_count']}</b>"
            f" · выручка: <b>{revenue}</b>"
        )
    return "\n".join(lines)


# ─── Вход в раздел ──────────────────────────────────────────────────────────

@router.message(StateFilter("*"), F.text == "📈 Откуда клиенты")
async def msg_traffic_entry(message: Message, state: FSMContext):
    """
    Вход в раздел. Удаляем тап-сообщение «📈 Откуда клиенты» и редактируем
    единую админ-панель — иначе каждый клик плодит новое сообщение, и чат
    быстро засоряется.
    """
    await state.clear()
    delete_in_bg(message)
    stats = await aggregate_by_source()
    await edit_panel(
        message.bot, message.chat.id,
        _render_sources_text(stats),
        _sources_keyboard(stats),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "traffic_list")
async def cb_traffic_list(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    stats = await aggregate_by_source()
    await edit_panel_with_callback(
        callback,
        _render_sources_text(stats),
        _sources_keyboard(stats),
        parse_mode="HTML",
    )
    await callback.answer()


# ─── Детали источника ───────────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^traffic_src_(\d+)$"))
async def cb_traffic_src(callback: CallbackQuery):
    source_id = int(callback.data.split("_")[-1])
    src = await get_source_by_id(source_id)
    if not src:
        await callback.answer("Источник не найден.", show_alert=True)
        return
    username = await _bot_username(callback.bot)
    link = _deep_link(username, src["code"])
    text = (
        f"<b>{src['label']}</b>\n"
        f"код: <code>{src['code']}</code>\n\n"
        f"<i>ссылка для Instagram / канала:</i>\n"
        f"<code>{link}</code>\n\n"
        f"<i>жми «📱 QR для печати» чтобы получить картинку</i>"
    )
    await edit_panel_with_callback(
        callback, text, _source_detail_keyboard(source_id),
        parse_mode="HTML",
    )
    await callback.answer()


# ─── QR ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^traffic_qr_(\d+)$"))
async def cb_traffic_qr(callback: CallbackQuery):
    source_id = int(callback.data.split("_")[-1])
    src = await get_source_by_id(source_id)
    if not src:
        await callback.answer("Источник не найден.", show_alert=True)
        return

    from utils.salon_info import get_salon_name

    username = await _bot_username(callback.bot)
    link = _deep_link(username, src["code"])
    # Заголовок плаката — label источника («Зеркало», «Instagram bio»).
    # Сверху мелко — название салона, если задано в настройках.
    salon_name = await get_salon_name()
    try:
        png = generate_qr(
            link,
            source_label=src["label"],
            salon_name=salon_name,
        )
    except Exception:
        logger.exception("QR generation failed for source=%s", src["code"])
        await callback.answer("Не удалось сгенерить QR.", show_alert=True)
        return

    file = BufferedInputFile(png, filename=f"qr_{src['code']}.png")
    await callback.message.answer_photo(
        photo=file,
        caption=(
            f"📱 <b>{src['label']}</b>\n"
            f"код: <code>{src['code']}</code>\n\n"
            f"печатай на A5. снизу/сверху оставь белое поле — QR считывается с метра."
        ),
        parse_mode="HTML",
    )
    await callback.answer()


# ─── Удаление источника ─────────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^traffic_del_(\d+)$"))
async def cb_traffic_del(callback: CallbackQuery):
    source_id = int(callback.data.split("_")[-1])
    src = await get_source_by_id(source_id)
    if not src:
        await callback.answer("Уже удалён.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ да, удалить", callback_data=f"traffic_del_yes_{source_id}")],
        [InlineKeyboardButton(text="↩️ отмена", callback_data=f"traffic_src_{source_id}")],
    ])
    await edit_panel_with_callback(
        callback,
        f"Удалить источник <b>{src['label']}</b> (<code>{src['code']}</code>)?\n\n"
        f"<i>клиенты, пришедшие с этого кода, остаются в статистике,\n"
        f"но новые QR/ссылки с ним не создашь.</i>",
        kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^traffic_del_yes_(\d+)$"))
async def cb_traffic_del_yes(callback: CallbackQuery, state: FSMContext):
    source_id = int(callback.data.split("_")[-1])
    ok = await delete_source(source_id)
    await callback.answer("Удалён." if ok else "Не удалось удалить.", show_alert=False)
    await cb_traffic_list(callback, state)


# ─── Добавление источника (FSM) ─────────────────────────────────────────────

@router.callback_query(F.data == "traffic_add")
async def cb_traffic_add(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.traffic_source_add_code)
    await edit_panel_with_callback(
        callback,
        "<b>Новый источник</b> — шаг 1/2\n\n"
        "Пришли <b>код</b> для ссылки (латиница, цифры, <code>_</code>/<code>-</code>, 2-32 симв.).\n\n"
        "Пример: <code>ig_bio</code>, <code>story_apr20</code>, <code>friend_anya</code>.\n"
        "Он подставится в <code>t.me/bot?start=&lt;код&gt;</code>.",
        admin_cancel_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.traffic_source_add_code)
async def msg_traffic_code(message: Message, state: FSMContext):
    # Удаляем тап-сообщение клиента с введённым кодом — не засоряем чат.
    try:
        await message.delete()
    except Exception:
        pass
    code = normalize_code(message.text or "")
    if not code:
        await edit_panel(
            message.bot, message.chat.id,
            "⚠️ Неверный формат. Только латиница/цифры/<code>_-</code>, 2-32 симв.\n"
            "Пришли заново или нажми <i>↩️ Отмена</i>.",
            admin_cancel_keyboard(),
            parse_mode="HTML",
        )
        return
    from db.traffic import get_source_by_code
    if await get_source_by_code(code):
        await edit_panel(
            message.bot, message.chat.id,
            f"⚠️ Код <code>{code}</code> уже существует. Пришли другой.",
            admin_cancel_keyboard(),
            parse_mode="HTML",
        )
        return
    await state.update_data(new_source_code=code)
    await state.set_state(AdminStates.traffic_source_add_label)
    await edit_panel(
        message.bot, message.chat.id,
        f"Ок, код <code>{code}</code>.\n\n"
        f"Теперь <b>подпись</b> (человекочитаемая, до 64 симв.).\n"
        f"Пример: <code>Instagram bio</code>, <code>Сторис 20 апреля</code>.",
        admin_cancel_keyboard(),
        parse_mode="HTML",
    )


@router.message(AdminStates.traffic_source_add_label)
async def msg_traffic_label(message: Message, state: FSMContext):
    label = (message.text or "").strip()
    if not label or len(label) > 64:
        try:
            await message.delete()
        except Exception:
            pass
        await edit_panel(
            message.bot, message.chat.id,
            "⚠️ Подпись обязательна, макс 64 симв. Пришли ещё раз.",
            admin_cancel_keyboard(),
            parse_mode="HTML",
        )
        return
    data = await state.get_data()
    code = data.get("new_source_code")
    if not code:
        await state.clear()
        await message.answer("Что-то пошло не так, начни заново.")
        return
    source_id = await create_source(code, label)
    await state.clear()
    # Удаляем тап-сообщение клиента с введённым label — он уже в state.
    try:
        await message.delete()
    except Exception:
        pass
    if source_id is None:
        await edit_panel(
            message.bot, message.chat.id,
            f"⚠️ Не удалось создать (код <code>{code}</code> уже занят?).",
            parse_mode="HTML",
        )
        return

    # Показываем обновлённый список в той же живой панели — одно сообщение,
    # а не два раздельных «создано» + «список».
    stats = await aggregate_by_source()
    await edit_panel(
        message.bot, message.chat.id,
        _render_sources_text(stats),
        _sources_keyboard(stats),
        parse_mode="HTML",
    )
