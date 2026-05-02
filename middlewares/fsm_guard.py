"""
Middleware: если пользователь в FSM-состоянии от предыдущей сессии бота
(рестарт с persistent storage), мягко сбросить состояние.

Для MemoryStorage состояние теряется при рестарте само, но middleware
ставит session-маркер чтобы корректно работать с любым типом storage.
"""
import logging
import uuid
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, TelegramObject

logger = logging.getLogger(__name__)

# Ключ маркера в FSM data
_SESSION_KEY = "_fsm_session"


class FSMGuardMiddleware(BaseMiddleware):
    """
    При каждом запуске бота генерируется уникальный session_id.
    Когда пользователь входит в FSM, маркер сохраняется в data.
    Если при следующем update маркер не совпадает — значит бот
    был перезапущен, и state нужно сбросить.
    """

    def __init__(self) -> None:
        self._session_id = str(uuid.uuid4())

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        state: FSMContext | None = data.get("state")
        if state is None:
            return await handler(event, data)

        current_state = await state.get_state()
        if current_state is None:
            return await handler(event, data)

        fsm_data = await state.get_data()
        session = fsm_data.get(_SESSION_KEY)

        if session is None:
            # Первый вход в FSM в этой сессии — ставим маркер, пропускаем
            await state.update_data({_SESSION_KEY: self._session_id})
            return await handler(event, data)

        if session != self._session_id:
            # Маркер от старой сессии → бот был перезапущен
            logger.info(
                "FSM state=%s от предыдущей сессии бота, сброс",
                current_state,
            )
            await state.clear()

            if isinstance(event, Message):
                await event.answer(
                    "Бот был перезапущен. Пожалуйста, начните заново: /start"
                )
            elif isinstance(event, CallbackQuery):
                await event.answer(
                    "Бот был перезапущен. Нажмите /start",
                    show_alert=True,
                )
            return

        # Маркер совпадает — всё ок
        return await handler(event, data)
