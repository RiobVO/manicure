"""
Централизованный алерт unhandled exceptions в приватный Telegram-канал.

Принципы:
  • Никогда не валит основной бот: любой сбой отправки глотается в warning.
  • Хранит last_error и start_time в памяти процесса — для /status-команды.
  • PII не пишется: user_id пишем (не phone/name), текст сообщения режем до 50 символов.
  • Если ERROR_CHAT_ID пуст — только в stderr и в last_error, наружу ничего.
"""
import logging
import traceback
from datetime import datetime
from typing import Any

from aiogram import Bot

from config import ERROR_CHAT_ID, TENANT_SLUG
from utils.timezone import now_local

logger = logging.getLogger(__name__)

_last_error: dict[str, Any] | None = None
_start_time: datetime | None = None


def mark_started() -> None:
    """Зафиксировать момент старта бота — нужен для uptime в /status."""
    global _start_time
    _start_time = now_local()


def get_start_time() -> datetime | None:
    return _start_time


def get_last_error() -> dict[str, Any] | None:
    return _last_error


async def report_error(
    bot: Bot,
    exc: BaseException,
    context: str = "",
    user_id: int | None = None,
) -> None:
    """
    Запомнить ошибку и (если настроено) отправить её в канал.

    Проглатывает любые сбои отправки — алертинг не должен ронять бот.
    """
    global _last_error

    exc_type = type(exc).__name__
    exc_msg = str(exc) or "(no message)"

    _last_error = {
        "at": now_local(),
        "type": exc_type,
        "msg": exc_msg[:200],
        "context": context,
    }

    if ERROR_CHAT_ID is None:
        return

    tb_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    if len(tb_text) > 3000:
        tb_text = "…\n" + tb_text[-3000:]

    parts = [f"🔥 <b>[{TENANT_SLUG}]</b> {_esc(exc_type)}"]
    if context:
        parts.append(f"<i>{_esc(context)}</i>")
    if user_id is not None:
        parts.append(f"user_id=<code>{user_id}</code>")
    parts.append(f"\n<pre>{_esc(tb_text)}</pre>")

    text = "\n".join(parts)
    if len(text) > 4000:
        text = text[:3990] + "\n…(обрезано)"

    try:
        await bot.send_message(
            chat_id=ERROR_CHAT_ID,
            text=text,
            parse_mode="HTML",
        )
    except Exception as send_exc:
        # Алертинг не падает — иначе рекурсия и потеря полезных логов.
        logger.warning("Не удалось отправить алерт в TG chat=%s: %s", ERROR_CHAT_ID, send_exc)


def _esc(s: str) -> str:
    """HTML-escape для TG parse_mode=HTML."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
