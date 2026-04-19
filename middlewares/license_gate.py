"""
Middleware: блокирует все хендлеры когда LicenseState == RESTRICTED.

Логика:
  • Режимы OK / GRACE / DEV — пропускаем всё.
  • RESTRICTED — отвечаем на /start фиксированным сообщением про лицензию
    и проглатываем остальное (не роняя, не давая работать).

Никаких исключений. Никаких обходных путей внутри middleware —
если автор хочет разрешить какую-то команду даже в restricted, пусть это
здесь будет видно явно одним местом.
"""
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from utils.license import LicenseState, LicenseMode

logger = logging.getLogger(__name__)


class LicenseGateMiddleware(BaseMiddleware):
    def __init__(self, state: LicenseState, contact: str) -> None:
        self._state = state
        self._contact = contact or "поставщика бота"

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if self._state.mode != LicenseMode.RESTRICTED:
            return await handler(event, data)

        # Restricted: пропускаем только команду /start с фиксированным ответом.
        if isinstance(event, Message):
            text = (event.text or "").strip()
            if text.startswith("/start"):
                # parse_mode обязателен: в шаблоне есть <i>…</i>; Bot создаётся без DefaultBotProperties.
                await event.answer(self._restricted_text(), parse_mode="HTML")
            # Остальные сообщения игнорируем молча — не отвечаем, не роняем.
            return None

        if isinstance(event, CallbackQuery):
            # На кнопки отвечаем всплывающим алертом, иначе TG крутит loading.
            await event.answer("Лицензия бота истекла", show_alert=True)
            return None

        # Любой другой тип апдейта — просто проглатываем.
        return None

    def _restricted_text(self) -> str:
        reason = self._state.reason or "нет данных"
        return (
            "🔒 Лицензия бота истекла.\n\n"
            f"Обратитесь к {self._contact} для продления.\n\n"
            f"<i>Причина: {reason}</i>"
        )
