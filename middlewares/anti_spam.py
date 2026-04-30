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

# Два слоя anti-spam:
#
# 1) MIN_INTERVAL_MS = 1500 мс — между ОДИНАКОВЫМИ кликами от одного user'а
#    на ту же кнопку. Защита от нервного двойного-тройного тапа на одну
#    и ту же кнопку (повторный клик «не нажалось ли?»).
#
# 2) MIN_USER_INTERVAL_MS = 400 мс — между ЛЮБЫМИ кликами от одного user'а,
#    независимо от data. Это критично потому что у Telegram Bot API лимит
#    «1 edit_message/сек на чат». Когда клиент быстро проходит букинг
#    (категория → услуга → мастер → дата → время — 5+ кликов за 3-5 сек),
#    каждый клик делает edit_text. На 8-9 кликах TG возвращает
#    429 Too Many Requests с retry_after=3. aiogram ждёт 3 секунды и
#    ретраит — клиент видит «залипание на 3 секунды». 400мс ограничивает
#    частоту edit_text до ~2.5/сек в худшем случае, что ниже опасной зоны.
#    Осознанный flow букинга редко идёт быстрее 600мс между шагами.
MIN_INTERVAL_MS = 1500
MIN_USER_INTERVAL_MS = 400

# Раз в сколько событий чистим устаревшие записи (старше MIN_INTERVAL_MS * 10).
# 1000 — компромисс: не часто, но достаточно чтобы dict не пух при долгом аптайме.
GC_EVERY_N = 1000


class AntiSpamCallbackMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        # (user_id, callback.data) → timestamp последнего тапа на ту же кнопку.
        self._last_same: dict[tuple[int, str], float] = {}
        # user_id → timestamp ЛЮБОГО последнего callback'а (защита от Telegram
        # rate-limit «1 edit_message/сек на чат» при быстрой навигации).
        self._last_any: dict[int, float] = {}
        self._tick = 0

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, CallbackQuery) or not event.data or not event.from_user:
            return await handler(event, data)

        user_id = event.from_user.id
        key = (user_id, event.data)
        now_ms = time.monotonic() * 1000

        last_same = self._last_same.get(key)
        last_any = self._last_any.get(user_id)
        self._last_same[key] = now_ms
        self._last_any[user_id] = now_ms

        # Периодический GC чтобы dict не разрастался при долгом аптайме.
        self._tick += 1
        if self._tick >= GC_EVERY_N:
            self._tick = 0
            cutoff_same = now_ms - MIN_INTERVAL_MS * 10
            cutoff_any = now_ms - MIN_USER_INTERVAL_MS * 25
            self._last_same = {k: v for k, v in self._last_same.items() if v >= cutoff_same}
            self._last_any = {k: v for k, v in self._last_any.items() if v >= cutoff_any}

        # Слой 1: повторный тап на ту же кнопку — нервный спам.
        if last_same is not None and (now_ms - last_same) < MIN_INTERVAL_MS:
            try:
                await event.answer()
            except Exception:
                pass
            logger.debug(
                "anti-spam[same]: дропнут повтор user=%s data=%r delta=%dms",
                user_id, event.data, int(now_ms - last_same),
            )
            return None

        # Слой 2: слишком частые любые клики — защита от Telegram rate-limit.
        # Без него бот делал >1 edit_text/сек на чат, TG возвращал 429, aiogram
        # ждал 3 секунды и ретраил → клиент видел «залипание на каждом 8-9 тапе».
        if last_any is not None and (now_ms - last_any) < MIN_USER_INTERVAL_MS:
            try:
                await event.answer()
            except Exception:
                pass
            logger.debug(
                "anti-spam[rate]: дропнут частый клик user=%s data=%r delta=%dms",
                user_id, event.data, int(now_ms - last_any),
            )
            return None

        return await handler(event, data)
