"""Логи действий админа и CRUD админов."""

import logging
from typing import Any

import aiosqlite

from db.connection import get_db, _dict_rows

logger = logging.getLogger(__name__)


async def log_admin_action(admin_id: int, action: str, target_type: str = "",
                           target_id: int = 0, details: str = "") -> None:
    """Записать действие админа в лог."""
    db = await get_db()
    await db.execute(
        "INSERT INTO admin_logs (admin_id, action, target_type, target_id, details) VALUES (?, ?, ?, ?, ?)",
        (admin_id, action, target_type, target_id, details)
    )
    await db.commit()


async def get_admin_logs(
    admin_id: int | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    """Получить логи действий админа."""
    if admin_id:
        return await _dict_rows(
            "SELECT * FROM admin_logs WHERE admin_id = ? ORDER BY created_at DESC LIMIT ?",
            (admin_id, limit),
        )
    return await _dict_rows(
        "SELECT * FROM admin_logs ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )


async def add_admin(user_id: int, added_by: int, comment: str = "") -> None:
    """Добавить админа. Дубль (UNIQUE по user_id) — не ошибка."""
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO admins (user_id, added_by, comment) VALUES (?, ?, ?)",
            (user_id, added_by, comment)
        )
        await db.commit()
    except aiosqlite.IntegrityError as exc:
        logger.debug("Admin already exists: user_id=%s (%s)", user_id, exc)


async def remove_admin(user_id: int) -> bool:
    """Удалить админа. Возвращает True если удалён."""
    db = await get_db()
    cursor = await db.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
    await db.commit()
    return cursor.rowcount > 0


async def get_db_admins() -> list[dict[str, Any]]:
    """Получить всех админов из БД (не включая тех что в .env)."""
    return await _dict_rows("SELECT * FROM admins ORDER BY added_at DESC")


async def is_db_admin(user_id: int) -> bool:
    """Проверить, есть ли в БД как админ."""
    db = await get_db()
    cursor = await db.execute("SELECT COUNT(*) FROM admins WHERE user_id = ?", (user_id,))
    return (await cursor.fetchone())[0] > 0
