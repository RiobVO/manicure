"""
Трекер «живой панели» администратора — один ID на каждый чат.
"""
import asyncio
import logging
from collections import OrderedDict

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, ReplyKeyboardMarkup

logger = logging.getLogger(__name__)

_MAX_LOCKS = 500
_MAX_PANEL_CACHE = 1000

_panel_msg_ids: "OrderedDict[int, int]" = OrderedDict()
_locks: dict[int, asyncio.Lock] = {}
_reply_kb_cache: "OrderedDict[int, ReplyKeyboardMarkup]" = OrderedDict()


def get_panel_lock(chat_id: int) -> asyncio.Lock:
    lock = _locks.get(chat_id)
    if lock is None:
        if len(_locks) >= _MAX_LOCKS:
            # Освобождаем свободные locks (никто не держит семафор — безопасно удалить)
            stale = [cid for cid, l in _locks.items() if not l.locked()]
            for cid in stale[: len(_locks) - _MAX_LOCKS + 1]:
                _locks.pop(cid, None)
        lock = asyncio.Lock()
        _locks[chat_id] = lock
    return lock


def get_panel_msg_id(chat_id: int) -> int | None:
    return _panel_msg_ids.get(chat_id)


def set_panel_msg_id(chat_id: int, msg_id: int) -> None:
    # FIFO eviction: старые чаты вытесняются при переполнении
    if chat_id in _panel_msg_ids:
        _panel_msg_ids.move_to_end(chat_id)
    _panel_msg_ids[chat_id] = msg_id
    while len(_panel_msg_ids) > _MAX_PANEL_CACHE:
        _panel_msg_ids.popitem(last=False)


def set_reply_kb(chat_id: int, kb: ReplyKeyboardMarkup) -> None:
    """Запомнить reply keyboard для этого чата."""
    if chat_id in _reply_kb_cache:
        _reply_kb_cache.move_to_end(chat_id)
    _reply_kb_cache[chat_id] = kb
    while len(_reply_kb_cache) > _MAX_PANEL_CACHE:
        _reply_kb_cache.popitem(last=False)


def clear_panel_msg_id(chat_id: int) -> None:
    _panel_msg_ids.pop(chat_id, None)


async def edit_panel(
    bot: Bot,
    chat_id: int,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
) -> None:
    """
    Редактирует отслеживаемое сообщение панели.
    При ошибке — удаляет старое и создаёт новое.
    Блокировка asyncio.Lock предотвращает дубли при быстрых кликах.
    НЕ отправляет reply keyboard — это делает вызывающий код.
    """
    lock = get_panel_lock(chat_id)
    async with lock:
        nav_id = get_panel_msg_id(chat_id)
        if nav_id:
            try:
                await bot.edit_message_text(
                    text, chat_id=chat_id, message_id=nav_id,
                    reply_markup=markup, parse_mode=parse_mode,
                )
                return
            except TelegramBadRequest:
                logger.debug("Panel msg %s not editable, recreating", nav_id)
                try:
                    await bot.delete_message(chat_id, nav_id)
                except TelegramBadRequest:
                    pass  # уже удалено
                clear_panel_msg_id(chat_id)

        sent = await bot.send_message(chat_id, text, reply_markup=markup, parse_mode=parse_mode)
        set_panel_msg_id(chat_id, sent.message_id)


async def edit_panel_with_callback(
    callback: CallbackQuery,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
) -> None:
    """
    Универсальный helper для callback-ов:
    1. Если callback.message == панель → редактируем напрямую
    2. Иначе → edit_panel (с блокировкой)
    """
    chat_id = callback.message.chat.id
    panel_id = get_panel_msg_id(chat_id)

    if panel_id and callback.message.message_id == panel_id:
        try:
            await callback.message.edit_text(text, reply_markup=markup, parse_mode=parse_mode)
            return
        except TelegramBadRequest:
            logger.debug("Direct panel edit failed for chat %s, falling back", chat_id)
            clear_panel_msg_id(chat_id)

    await edit_panel(callback.bot, chat_id, text, markup, parse_mode)


# ─── Фоновый delete (оптимизация) ────────────────────────────────────────────
# asyncio хранит только weak-refs на таски, без strong-ref-сета GC соберёт
# _safe() до реального delete. Поэтому держим set + discard в done-callback.
_delete_bg_tasks: set[asyncio.Task] = set()


def delete_in_bg(message: Message) -> None:
    """
    Удалить сообщение в фоне. Не блокирует вызывающий код на Telegram round-trip
    (~240мс в dev, ~100мс на VPS). Ошибки (сообщение уже удалено, нет прав,
    >48ч) глотаются — UX не страдает.

    Использовать вместо `try: await message.delete() except: pass` везде,
    где delete — не жизненно важный шаг (тап reply-кнопок, очистка старых
    сообщений, закрытие формы).
    """
    async def _safe() -> None:
        try:
            await message.delete()
        except Exception:
            pass
    task = asyncio.create_task(_safe())
    _delete_bg_tasks.add(task)
    task.add_done_callback(_delete_bg_tasks.discard)
