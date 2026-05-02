"""CRUD мастеров и расписание мастеров."""

from datetime import datetime
from typing import Any

from db.connection import get_db, _dict_rows, _dict_row


async def get_active_masters() -> list[dict[str, Any]]:
    """Активные мастера, отсортированные по sort_order."""
    return await _dict_rows(
        "SELECT * FROM masters WHERE is_active = 1 ORDER BY sort_order, id"
    )


async def get_all_masters() -> list[dict[str, Any]]:
    """Все мастера для админ-панели."""
    return await _dict_rows(
        "SELECT * FROM masters ORDER BY sort_order, id"
    )


async def get_master(master_id: int) -> dict[str, Any] | None:
    return await _dict_row("SELECT * FROM masters WHERE id = ?", (master_id,))


async def create_master(
    user_id: int | None,
    name: str,
    photo_file_id: str = "",
    bio: str = "",
) -> int:
    """Создаёт мастера и копирует weekly_schedule как его начальное расписание."""
    db = await get_db()
    cursor = await db.execute(
        "INSERT INTO masters (user_id, name, photo_file_id, bio) VALUES (?, ?, ?, ?)",
        (user_id, name, photo_file_id, bio),
    )
    await db.commit()
    master_id = cursor.lastrowid
    await seed_master_schedule(master_id)
    return master_id


async def update_master(master_id: int, **fields: Any) -> None:
    """Обновить произвольные поля мастера. Допустимые ключи: name, user_id, photo_file_id, bio, is_active, sort_order."""
    allowed = {"name", "user_id", "photo_file_id", "bio", "is_active", "sort_order"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    db = await get_db()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    await db.execute(
        f"UPDATE masters SET {set_clause} WHERE id = ?",
        (*updates.values(), master_id),
    )
    await db.commit()


async def toggle_master_active(master_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE masters SET is_active = 1 - is_active WHERE id = ?",
        (master_id,),
    )
    await db.commit()


async def seed_master_schedule(master_id: int) -> None:
    """Копирует weekly_schedule в master_schedule для нового мастера."""
    db = await get_db()
    rows = await _dict_rows("SELECT weekday, work_start, work_end FROM weekly_schedule")
    for row in rows:
        await db.execute(
            """INSERT OR IGNORE INTO master_schedule (master_id, weekday, work_start, work_end)
               VALUES (?, ?, ?, ?)""",
            (master_id, row["weekday"], row["work_start"], row["work_end"]),
        )
    await db.commit()


async def get_master_schedule(master_id: int) -> dict[int, dict[str, Any]]:
    """Расписание мастера: {weekday: {work_start, work_end}}."""
    rows = await _dict_rows(
        "SELECT weekday, work_start, work_end FROM master_schedule WHERE master_id = ? ORDER BY weekday",
        (master_id,),
    )
    return {r["weekday"]: {"work_start": r["work_start"], "work_end": r["work_end"]} for r in rows}


async def get_day_schedule_for_master(master_id: int, date_str: str) -> tuple[int, int] | None:
    """
    Рабочие часы мастера на дату.
    Возвращает (work_start, work_end) или None если день — выходной/заблокированный.
    """
    # Явный выходной: blocked_slots с is_day_off=1 для этого мастера или глобально
    rows = await _dict_rows(
        """SELECT id FROM blocked_slots
           WHERE date = ? AND is_day_off = 1
             AND (master_id = ? OR master_id IS NULL)
        """,
        (date_str, master_id),
    )
    if rows:
        return None

    weekday = datetime.strptime(date_str, "%Y-%m-%d").weekday()
    row = await _dict_row(
        "SELECT work_start, work_end FROM master_schedule WHERE master_id = ? AND weekday = ?",
        (master_id, weekday),
    )
    if not row or row["work_start"] is None:
        return None  # выходной по расписанию

    return row["work_start"], row["work_end"]


async def get_day_off_weekdays_for_master(master_id: int) -> frozenset[int]:
    """Дни недели, помеченные выходными в расписании мастера."""
    rows = await _dict_rows(
        "SELECT weekday FROM master_schedule WHERE master_id = ? AND work_start IS NULL",
        (master_id,),
    )
    return frozenset(r["weekday"] for r in rows)


async def get_time_blocks_for_master(master_id: int, date_str: str) -> list[tuple[str, str]]:
    """Диапазоны заблокированного времени для мастера (включая глобальные блокировки)."""
    rows = await _dict_rows(
        """SELECT time_start, time_end FROM blocked_slots
           WHERE date = ? AND is_day_off = 0
             AND time_start IS NOT NULL AND time_end IS NOT NULL
             AND (master_id = ? OR master_id IS NULL)
        """,
        (date_str, master_id),
    )
    return [(r["time_start"], r["time_end"]) for r in rows]


async def delete_master(master_id: int) -> bool:
    """Удалить мастера. Возвращает False если у него есть записи (любого статуса) —
    историю сохраняем, мастер должен быть деактивирован, не удалён."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT COUNT(*) FROM appointments WHERE master_id = ?",
        (master_id,),
    )
    if (await cursor.fetchone())[0] > 0:
        return False
    await db.execute("DELETE FROM master_schedule WHERE master_id = ?", (master_id,))
    await db.execute("DELETE FROM blocked_slots WHERE master_id = ?", (master_id,))
    await db.execute("DELETE FROM masters WHERE id = ?", (master_id,))
    await db.commit()
    return True
