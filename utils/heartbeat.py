"""
Heartbeat к центральному endpoint автора — «я жив, я работаю».

Важно:
  • Провал отправки НЕ блокирует бот. Это инфо для автора, не контроль доступа.
  • Если HEARTBEAT_URL пуст — задача не регистрируется вовсе.
  • PII никакого: только tenant_slug, license_id, версия, timestamp.
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from config import HEARTBEAT_URL, TENANT_SLUG
from utils.timezone import now_local

logger = logging.getLogger(__name__)

# Версия, которую сообщает heartbeat. Поднимать вручную при значимых релизах.
APP_VERSION = "1.0.0"


async def send_heartbeat(license_id: str | None) -> None:
    """Отправить один heartbeat. Проглатывает любые сетевые/HTTP сбои."""
    if not HEARTBEAT_URL:
        return

    payload: dict[str, Any] = {
        "tenant_slug": TENANT_SLUG,
        "license_id": license_id or "",
        "version": APP_VERSION,
        "last_seen": now_local().isoformat(),
    }

    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(HEARTBEAT_URL, json=payload) as resp:
                if resp.status >= 400:
                    logger.warning(
                        "heartbeat HTTP %s на %s", resp.status, HEARTBEAT_URL
                    )
    except Exception as exc:
        # Сеть легла, DNS, HTTPS — не наша забота сейчас, мы просто пишем ворнинг.
        logger.warning("heartbeat не доставлен: %s", exc)
