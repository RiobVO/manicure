"""
Команда /status — ops-диагностика для владельца салона и автора.

Показывает: tenant_slug, uptime, размер БД, время последнего локального бэкапа,
статус Redis (ping), последняя увиденная ошибка. Всё — по /status-команде,
только для админов.
"""
import glob
import logging
import os
from datetime import datetime

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from config import DB_PATH, REDIS_URL, TENANT_SLUG
from utils.admin import is_admin
from utils.error_reporter import get_last_error, get_start_time
from utils.timezone import now_local

logger = logging.getLogger(__name__)

router = Router(name="admin_status")


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return

    lines: list[str] = ["<b>🛠 Status</b>", f"Салон: <code>{TENANT_SLUG}</code>"]

    start = get_start_time()
    if start is not None:
        delta = now_local() - start
        total_seconds = int(delta.total_seconds())
        h, rem = divmod(total_seconds, 3600)
        m, s = divmod(rem, 60)
        lines.append(f"Uptime: {h}ч {m}м {s}с")

    # размер БД
    try:
        size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
        lines.append(f"БД: {size_mb:.2f} MB ({DB_PATH})")
    except OSError as exc:
        lines.append(f"БД: ошибка чтения ({exc})")

    # последний локальный бэкап
    try:
        backups = sorted(glob.glob("backups/manicure_backup_*.db"))
        if backups:
            mtime = datetime.fromtimestamp(os.path.getmtime(backups[-1]))
            lines.append(
                f"Бэкап: {mtime.strftime('%Y-%m-%d %H:%M')} ({len(backups)} файлов)"
            )
        else:
            lines.append("Бэкапов ещё нет (запустится через 6ч или вручную)")
    except Exception as exc:
        lines.append(f"Бэкапы: ошибка чтения — {exc}")

    # Redis ping
    if REDIS_URL:
        try:
            from redis.asyncio import Redis

            client = Redis.from_url(REDIS_URL)
            await client.ping()
            await client.aclose()
            lines.append("Redis: ✅")
        except Exception as exc:
            lines.append(f"Redis: ❌ {type(exc).__name__}: {exc}")
    else:
        lines.append("Redis: — (MemoryStorage)")

    # последняя ошибка
    last_err = get_last_error()
    if last_err:
        at = last_err["at"].strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"\n⚠ Последняя ошибка {at}:")
        lines.append(f"<code>{last_err['type']}: {last_err['msg'][:200]}</code>")
        if last_err.get("context"):
            lines.append(f"ctx: <code>{last_err['context']}</code>")
    else:
        lines.append("\n✅ Ошибок с запуска: 0")

    await message.answer("\n".join(lines), parse_mode="HTML")
