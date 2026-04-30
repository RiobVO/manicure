"""
Anti-spam middleware для callback-кнопок.

Зачем:
  Когда клиент нервно тапает по одной и той же inline-кнопке несколько раз
  подряд, каждый тап создаёт независимый callback. Telegram-клиент крутит
  спиннер, пока не получит answerCallbackQuery. Пока первый callback
  обрабатывается (DB-запросы, edit_panel под мьютексом utils/panel.py), второй
  и третий ждут в очереди — и спиннер на них висит «как зависший».

Решение:
  В памяти хранится последний (user_id, callback.data) с временной меткой.
  Если тот же пользователь тапает ту же кнопку быстрее MIN_INTERVAL_MS — мы
  отвечаем пустым answerCallbackQuery (спиннер исчезает) и НЕ передаём
  событие хендлеру. Логика хендлера выполнится только для ПЕРВОГО клика.

Не трогаем:
  • message-события — там нет спиннера и нет такого же сценария спама;
  • разные callback.data от того же user — это нормальная навигация;
  • клики через MIN_INTERVAL_MS после предыдущего — это явное намерение клиента.

Память:
  Простой dict {(user_id, data) → last_ts}. Очищается раз в N тиков, чтобы
  не разрастался при долгом аптайме. На 80 салонов и десятки одновременных
  клиентов — пиковый размер ~500 записей, не страшно.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject

logger = logging.getLogger(__name__)

# Минимальный интервал между одинаковыми кликами от одного user'а.
# 600 мс достаточно: ниже этого — точно нервный спам, выше — осознанный
# повторный клик (например клиент решил вернуться назад на той же кнопке).
MIN_INTERVAL_MS = 600

# Раз в сколько событий чистим устаревшие записи (старше MIN_INTERVAL_MS * 10).
# 1000 — компромисс: не часто, но достаточно чтобы dict не пух при долгом аптайме.
GC_EVERY_N = 1000


class AntiSpamCallbackMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        # (user_id, callback.data) → timestamp последнего тапа в монотонных мс.
        self._last: dict[tuple[int, str], float] = {}
        self._tick = 0

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, CallbackQuery) or not event.data or not event.from_user:
            return await handler(event, data)

        key = (event.from_user.id, event.data)
        now_ms = time.monotonic() * 1000

        last = self._last.get(key)
        self._last[key] = now_ms

        # Периодический GC чтобы dict не разрастался при долгом аптайме.
        self._tick += 1
        if self._tick >= GC_EVERY_N:
            self._tick = 0
            cutoff = now_ms - MIN_INTERVAL_MS * 10
            self._last = {k: v for k, v in self._last.items() if v >= cutoff}

        if last is not None and (now_ms - last) < MIN_INTERVAL_MS:
            # Дребезг: глушим спиннер и не пускаем хендлер.
            try:
                await event.answer()
            except Exception:
                # Старый callback (>15 мин) — Telegram отказывает, это норм.
                pass
            logger.debug(
                "anti-spam: дропнут повторный callback user=%s data=%r delta=%dms",
                event.from_user.id, event.data, int(now_ms - last),
            )
            return None  # хендлер не вызывается

        return await handler(event, data)
