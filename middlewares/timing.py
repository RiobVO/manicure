"""
Middleware таймингов: меряет каждый handler и пишет в лог кто что сделал
и за сколько. Без неё aiogram пишет только «Update id=X is handled. Duration
Nms» — непонятно какой callback и на каком user_id тормозит.

Порог WARNING (SLOW_THRESHOLD_MS) по умолчанию 500 мс. Выше — жёлтый
флажок, значит что-то конкретное стоит оптимизировать. Успешные быстрые
апдейты в DEBUG — не захламляют INFO-лог.

Формат:
  INFO timing: msg user=123 text='/start' duration=231ms
  WARNING timing: cb user=123 data='confirm_yes' duration=1842ms
"""
from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

logger = logging.getLogger(__name__)

# Понижены пороги для UX-диагностики: всё что >200мс уже заметно
# пользователю как «секунда подвисло». До этого порог был 500мс — мы
# не ловили медленные хендлеры в зоне 300-500мс.
SLOW_THRESHOLD_MS = 200
VERY_SLOW_THRESHOLD_MS = 800

# Если duration выше LATENCY_HINT_THRESHOLD_MS — это явно про сеть/клиента,
# не про сервер. В лог пишем подсказку «не трогай код, проверь сеть».
LATENCY_HINT_THRESHOLD_MS = 50


class TimingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        t0 = time.monotonic()
        try:
            return await handler(event, data)
        finally:
            dt_ms = int((time.monotonic() - t0) * 1000)
            context = _describe(event)
            if context is None:
                return  # тип события, который нас не интересует
            level = (
                logging.ERROR if dt_ms > VERY_SLOW_THRESHOLD_MS
                else logging.WARNING if dt_ms > SLOW_THRESHOLD_MS
                else logging.DEBUG
            )
            logger.log(level, "timing: %s duration=%dms", context, dt_ms)


def _describe(event: TelegramObject) -> str | None:
    """Короткая строка-контекст: тип, user_id, что нажали/написали.

    Для CallbackQuery добавляем callback.id (короткий хеш Telegram'а) —
    это помогает диагностировать дубли: если в логах два подряд handler'а
    с разным callback.id и одинаковым data за 100мс — клиент тапнул дважды
    (anti-spam режет, но диагностика остаётся). Если разрыв >2с между
    одинаковыми callback.id — это retry самого Telegram, а не клиента.
    """
    if isinstance(event, Message):
        user_id = event.from_user.id if event.from_user else "?"
        text = (event.text or event.caption or "(no text)")[:60]
        return f"msg user={user_id} text={text!r}"
    if isinstance(event, CallbackQuery):
        user_id = event.from_user.id
        data = (event.data or "")[:60]
        cb_id = (event.id or "")[-8:]  # последние 8 символов — достаточно для диагностики
        return f"cb id={cb_id} user={user_id} data={data!r}"
    return None
