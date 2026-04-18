"""Настройки, недельное расписание, blocked_slots."""

from datetime import datetime
from typing import Any

from db.connection import get_db, _dict_rows, _dict_row


async def get_setting(key: str, default: str = "") -> str:
    db = await get_db()
    cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row[0] if row else default


async def set_setting(key: str, value: str) -> None:
    db = await get_db()
    await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    await db.commit()


async def get_all_settings() -> dict[str, str]:
    db = await get_db()
    cursor = await db.execute("SELECT key, value FROM settings")
    rows = await cursor.fetchall()
    return {k: v for k, v in rows}


async def get_weekly_schedule() -> dict[int, dict]:
    """Расписание по дням: {0: {weekday, work_start, work_end}, ...}"""
    rows = await _dict_rows(
        "SELECT weekday, work_start, work_end FROM weekly_schedule ORDER BY weekday"
    )
    return {r["weekday"]: r for r in rows}


async def get_day_schedule(date_str: str) -> tuple[int, int] | None:
    """
    Рабочие часы для конкретной даты по дню недели.
    Возвращает (work_start, work_end) или None если день — выходной.
    Если строки нет (нет данных) — возвращает дефолт (9, 19).
    """
    weekday = datetime.strptime(date_str, "%Y-%m-%d").weekday()
    row = await _dict_row(
        "SELECT work_start, work_end FROM weekly_schedule WHERE weekday = ?", (weekday,)
    )
    if not row:
        return (9, 19)  # нет данных — дефолт
    if row["work_start"] is None:
        return None  # выходной
    return row["work_start"], row["work_end"]


async def update_weekday_schedule(weekday: int, work_start: int | None, work_end: int | None) -> None:
    """Обновить часы работы дня недели. work_start=None → выходной."""
    db = await get_db()
    await db.execute(
        "UPDATE weekly_schedule SET work_start = ?, work_end = ? WHERE weekday = ?",
        (work_start, work_end, weekday),
    )
    await db.commit()


async def is_day_off(date: str) -> bool:
    db = await get_db()
    cursor = await db.execute(
        "SELECT COUNT(*) FROM blocked_slots WHERE date = ? AND is_day_off = 1", (date,)
    )
    return (await cursor.fetchone())[0] > 0


async def get_time_blocks(date: str) -> list[tuple[str, str]]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT time_start, time_end FROM blocked_slots WHERE date = ? AND is_day_off = 0",
        (date,)
    )
    return await cursor.fetchall()


async def get_future_blocks() -> list[dict[str, Any]]:
    return await _dict_rows(
        """SELECT bs.id, bs.date, bs.time_start, bs.time_end, bs.is_day_off,
                  bs.reason, bs.master_id, m.name AS master_name
           FROM blocked_slots bs
           LEFT JOIN masters m ON m.id = bs.master_id
           WHERE bs.date >= date('now')
           ORDER BY bs.date, bs.time_start"""
    )


async def add_day_off(date: str, reason: str = "", master_id: int | None = None) -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO blocked_slots (date, is_day_off, reason, master_id) VALUES (?, 1, ?, ?)",
        (date, reason, master_id),
    )
    await db.commit()


async def add_time_block(
    date: str,
    time_start: str,
    time_end: str,
    reason: str = "",
    master_id: int | None = None,
) -> None:
    db = await get_db()
    await db.execute(
        """INSERT INTO blocked_slots (date, time_start, time_end, is_day_off, reason, master_id)
           VALUES (?, ?, ?, 0, ?, ?)""",
        (date, time_start, time_end, reason, master_id),
    )
    await db.commit()


async def delete_blocked_slot(block_id: int) -> None:
    db = await get_db()
    await db.execute("DELETE FROM blocked_slots WHERE id = ?", (block_id,))
    await db.commit()
