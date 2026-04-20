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


async def update_master_weekday(
    master_id: int,
    weekday: int,
    work_start: int | None,
    work_end: int | None,
) -> None:
    """Upsert строки master_schedule для мастера и дня недели.

    work_start=None, work_end=None → день помечен выходным.
    Используется админским редактором расписания. Мастер права на это не имеет."""
    db = await get_db()
    await db.execute(
        """INSERT INTO master_schedule (master_id, weekday, work_start, work_end)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(master_id, weekday) DO UPDATE SET
               work_start = excluded.work_start,
               work_end   = excluded.work_end""",
        (master_id, weekday, work_start, work_end),
    )
    await db.commit()


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


async def get_master_by_user_id(user_id: int) -> dict[str, Any] | None:
    """Возвращает активного мастера, привязанного к TG user_id, или None.
    Используется для role-routing и для загрузки данных кабинета."""
    return await _dict_row(
        "SELECT * FROM masters WHERE user_id = ? AND is_active = 1",
        (user_id,),
    )


async def get_active_masters_with_user_id() -> list[dict[str, Any]]:
    """Активные мастера с привязанным user_id — для построения masters-кеша.
    Мастера без user_id в кабинет не попадут и в кеше не нужны."""
    return await _dict_rows(
        "SELECT id, user_id, name FROM masters WHERE is_active = 1 AND user_id IS NOT NULL"
    )


async def get_master_appointments_today(
    master_id: int, date_str: str,
) -> list[dict[str, Any]]:
    """Записи мастера на указанную дату: scheduled + completed + no_show.
    Отменённые (cancelled) исключены — мастеру они не нужны."""
    return await _dict_rows(
        """SELECT id, time, name, phone, service_name, service_duration, status
           FROM appointments
           WHERE master_id = ? AND date = ?
             AND status IN ('scheduled', 'completed', 'no_show')
           ORDER BY time""",
        (master_id, date_str),
    )


async def get_master_appointments_upcoming(
    master_id: int, from_date: str, limit: int = 30,
) -> list[dict[str, Any]]:
    """Scheduled записи мастера от даты (включительно), ORDER BY date, time.
    Лимит 30 — чтобы экран не превращался в простыню; при переполнении
    показываем хвост «... и ещё N» на UI-слое."""
    return await _dict_rows(
        """SELECT id, date, time, name, phone, service_name, service_duration
           FROM appointments
           WHERE master_id = ? AND status = 'scheduled' AND date >= ?
           ORDER BY date, time
           LIMIT ?""",
        (master_id, from_date, limit),
    )


# ─── Self-serve day-off для мастера (v.3 Phase 1) ──────────────────────────
# Отгул хранится как строка в blocked_slots с is_day_off=1 и master_id.
# Это переиспользует существующий механизм — get_day_schedule_for_master уже
# читает blocked_slots и возвращает None. Отдельной таблицы не делаем.


async def add_master_day_off(master_id: int, date_str: str) -> int:
    """Поставить отгул мастеру на дату. Возвращает id созданной строки
    blocked_slots. Caller сам проверяет конфликты (count_master_scheduled_on_date)
    и идемпотентность (нет ли уже отгула на эту дату)."""
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO blocked_slots (date, is_day_off, reason, master_id)
           VALUES (?, 1, 'отгул мастера', ?)""",
        (date_str, master_id),
    )
    await db.commit()
    return cursor.lastrowid


async def delete_master_day_off(block_id: int, master_id: int) -> bool:
    """Удалить отгул. master_id — guard: чужие строки не трогаем,
    даже если block_id существует. True если удалено."""
    db = await get_db()
    cursor = await db.execute(
        """DELETE FROM blocked_slots
           WHERE id = ? AND master_id = ? AND is_day_off = 1""",
        (block_id, master_id),
    )
    await db.commit()
    return cursor.rowcount > 0


async def get_future_master_day_offs(master_id: int) -> list[dict[str, Any]]:
    """Будущие отгулы конкретного мастера, отсортированные по дате.
    Глобальные блокировки (master_id IS NULL) не включаем — мастер не может
    их ни поставить, ни убрать."""
    return await _dict_rows(
        """SELECT id, date FROM blocked_slots
           WHERE master_id = ? AND is_day_off = 1 AND date >= date('now')
           ORDER BY date""",
        (master_id,),
    )


async def count_master_scheduled_on_date(master_id: int, date_str: str) -> int:
    """Сколько scheduled записей у мастера на дату. Для conflict-guard
    перед постановкой отгула."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT COUNT(*) FROM appointments
           WHERE master_id = ? AND date = ? AND status = 'scheduled'""",
        (master_id, date_str),
    )
    return (await cursor.fetchone())[0]
