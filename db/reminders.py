"""Дедупликация напоминаний (sent_reminders)."""

import logging

import aiosqlite

from db.connection import get_db

logger = logging.getLogger(__name__)


async def was_reminder_sent(appointment_id: int, reminder_type: str) -> bool:
    """Проверить, уже ли отправляли этот тип напоминания."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT COUNT(*) FROM sent_reminders WHERE appointment_id = ? AND reminder_type = ?",
        (appointment_id, reminder_type)
    )
    return (await cursor.fetchone())[0] > 0


async def mark_reminder_sent(appointment_id: int, reminder_type: str) -> None:
    """Отметить, что напоминание отправлено. Дубль (UNIQUE) — не ошибка."""
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO sent_reminders (appointment_id, reminder_type) VALUES (?, ?)",
            (appointment_id, reminder_type)
        )
        await db.commit()
    except aiosqlite.IntegrityError as exc:
        # UNIQUE-конфликт ожидаем (двойной тик планировщика), логируем в DEBUG.
        logger.debug(
            "Reminder already marked: appt=%s type=%s (%s)",
            appointment_id, reminder_type, exc,
        )
