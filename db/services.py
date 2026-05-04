"""CRUD услуг и аддонов."""

from typing import Any

from db.connection import get_db, _dict_rows, _dict_row


async def get_services(
    active_only: bool = True,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """
    category: 'hands' | 'feet' | None (без фильтра).
    """
    where: list[str] = []
    params: list[Any] = []
    if active_only:
        where.append("is_active = 1")
    if category is not None:
        where.append("category = ?")
        params.append(category)

    sql = "SELECT * FROM services"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY sort_order, id"
    return await _dict_rows(sql, params)


async def get_service_by_id(service_id: int) -> dict[str, Any] | None:
    return await _dict_row("SELECT * FROM services WHERE id = ?", (service_id,))


async def update_service_name(service_id: int, name: str) -> None:
    db = await get_db()
    await db.execute("UPDATE services SET name = ? WHERE id = ?", (name, service_id))
    await db.commit()


async def update_service_price(service_id: int, price: int) -> None:
    db = await get_db()
    await db.execute("UPDATE services SET price = ? WHERE id = ?", (price, service_id))
    await db.commit()


async def update_service_duration(service_id: int, duration: int) -> None:
    db = await get_db()
    await db.execute("UPDATE services SET duration = ? WHERE id = ?", (duration, service_id))
    await db.commit()


async def update_service_description(service_id: int, description: str) -> None:
    db = await get_db()
    await db.execute("UPDATE services SET description = ? WHERE id = ?", (description, service_id))
    await db.commit()


async def toggle_service_active(service_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE services SET is_active = 1 - is_active WHERE id = ?", (service_id,)
    )
    await db.commit()


async def delete_service(service_id: int) -> None:
    db = await get_db()
    await db.execute("DELETE FROM services WHERE id = ?", (service_id,))
    await db.commit()


async def add_service(name: str, price: int, duration: int, category: str = "hands") -> int:
    db = await get_db()
    # sort_order: кладём в конец списка, взяв max(existing)+1 атомарно
    # через подзапрос — чтобы новые услуги всегда были последними.
    cursor = await db.execute(
        """INSERT INTO services (name, price, duration, is_active, sort_order, category)
           VALUES (?, ?, ?, 1, COALESCE((SELECT MAX(sort_order) FROM services), 0) + 1, ?)""",
        (name, price, duration, category),
    )
    await db.commit()
    return cursor.lastrowid


async def update_service_category(service_id: int, category: str) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE services SET category = ? WHERE id = ?", (category, service_id)
    )
    await db.commit()


async def get_addons_for_service(service_id: int, active_only: bool = True) -> list[dict[str, Any]]:
    """Доп. опции для услуги."""
    if active_only:
        return await _dict_rows(
            "SELECT * FROM service_addons WHERE service_id = ? AND is_active = 1 ORDER BY sort_order, id",
            (service_id,),
        )
    return await _dict_rows(
        "SELECT * FROM service_addons WHERE service_id = ? ORDER BY sort_order, id",
        (service_id,),
    )


async def get_addon_by_id(addon_id: int) -> dict[str, Any] | None:
    return await _dict_row("SELECT * FROM service_addons WHERE id = ?", (addon_id,))


async def add_addon(service_id: int, name: str, price: int) -> int:
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO service_addons (service_id, name, price, sort_order)
           VALUES (?, ?, ?, COALESCE((SELECT MAX(sort_order) FROM service_addons WHERE service_id = ?), 0) + 1)""",
        (service_id, name, price, service_id),
    )
    await db.commit()
    return cursor.lastrowid


async def delete_addon(addon_id: int) -> None:
    db = await get_db()
    await db.execute("DELETE FROM service_addons WHERE id = ?", (addon_id,))
    await db.commit()


async def toggle_addon_active(addon_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE service_addons SET is_active = 1 - is_active WHERE id = ?", (addon_id,)
    )
    await db.commit()


async def service_has_future_appointments(service_id: int) -> bool:
    db = await get_db()
    cursor = await db.execute(
        """SELECT COUNT(*) FROM appointments
           WHERE service_id = ? AND status = 'scheduled' AND date >= date('now')""",
        (service_id,)
    )
    return (await cursor.fetchone())[0] > 0
