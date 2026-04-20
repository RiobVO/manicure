"""Тесты self-serve отгулов мастера (v.3 Phase 1).

Покрытие — DB-слой (4 новые функции в db/masters.py). Хендлеры в master.py
не тестируем — они read-through на эти же функции, а интеграционный ран
через aiogram требует мок TG-клиента, что выходит за scope «минитест».
"""
from db import (
    add_master_day_off,
    count_master_scheduled_on_date,
    create_master,
    delete_master_day_off,
    get_day_schedule_for_master,
    get_future_master_day_offs,
)
from db.connection import get_db


async def test_add_and_list_day_off(fresh_db):
    """Постановка отгула — появляется в get_future_master_day_offs с нужной датой."""
    master_id = await create_master(user_id=None, name="Анна")

    block_id = await add_master_day_off(master_id, "2099-12-31")
    assert block_id > 0

    day_offs = await get_future_master_day_offs(master_id)
    assert len(day_offs) == 1
    assert day_offs[0]["id"] == block_id
    assert day_offs[0]["date"] == "2099-12-31"


async def test_day_off_blocks_schedule(fresh_db):
    """Главный инвариант: get_day_schedule_for_master читает blocked_slots
    и возвращает None для дня с отгулом. Ради этого всё затевалось."""
    master_id = await create_master(None, "Анна")
    # До отгула — день рабочий (дефолт 9-19 по weekly_schedule).
    assert await get_day_schedule_for_master(master_id, "2099-12-31") == (9, 19)

    await add_master_day_off(master_id, "2099-12-31")

    assert await get_day_schedule_for_master(master_id, "2099-12-31") is None


async def test_delete_day_off(fresh_db):
    """Удаление своего отгула — rowcount=True, список пустеет."""
    master_id = await create_master(None, "Анна")
    block_id = await add_master_day_off(master_id, "2099-11-30")

    removed = await delete_master_day_off(block_id, master_id)
    assert removed is True
    assert await get_future_master_day_offs(master_id) == []
    # И день снова рабочий
    assert await get_day_schedule_for_master(master_id, "2099-11-30") == (9, 19)


async def test_cannot_delete_foreign_day_off(fresh_db):
    """master_id в DELETE-guard защищает от подмены block_id через тухлый
    callback: мастер Б не может удалить отгул мастера А, даже зная id."""
    m_a = await create_master(None, "Анна")
    m_b = await create_master(None, "Белла")

    block_id = await add_master_day_off(m_a, "2099-10-15")
    removed_by_b = await delete_master_day_off(block_id, m_b)
    assert removed_by_b is False

    # Отгул А по-прежнему на месте
    day_offs_a = await get_future_master_day_offs(m_a)
    assert len(day_offs_a) == 1
    assert day_offs_a[0]["id"] == block_id


async def test_future_list_excludes_past(fresh_db):
    """Прошлые отгулы не попадают в get_future — их мастеру показывать незачем.
    Вставляем прошлую дату напрямую через INSERT, чтобы обойти тривиальную
    проверку в хендлере (её нет в add_master_day_off)."""
    master_id = await create_master(None, "Анна")
    db = await get_db()
    await db.execute(
        "INSERT INTO blocked_slots (date, is_day_off, reason, master_id) "
        "VALUES (?, 1, 'old', ?)",
        ("2000-01-01", master_id),
    )
    await db.commit()

    future_block = await add_master_day_off(master_id, "2099-06-15")

    day_offs = await get_future_master_day_offs(master_id)
    assert [d["id"] for d in day_offs] == [future_block]


async def test_future_list_only_own_master(fresh_db):
    """Изолируем мастеров друг от друга и от глобальных блокировок.
    Глобальный блок (master_id IS NULL) в списке тоже не должен появляться —
    мастер им не управляет."""
    m_a = await create_master(None, "Анна")
    m_b = await create_master(None, "Белла")

    await add_master_day_off(m_a, "2099-07-01")
    await add_master_day_off(m_b, "2099-07-02")

    # Глобальный отгул (не привязан к мастеру) — через INSERT, add_master_day_off
    # такого варианта не предоставляет.
    db = await get_db()
    await db.execute(
        "INSERT INTO blocked_slots (date, is_day_off, reason, master_id) "
        "VALUES (?, 1, 'санобработка', NULL)",
        ("2099-07-03",),
    )
    await db.commit()

    a_list = await get_future_master_day_offs(m_a)
    assert [d["date"] for d in a_list] == ["2099-07-01"]

    b_list = await get_future_master_day_offs(m_b)
    assert [d["date"] for d in b_list] == ["2099-07-02"]


async def test_count_scheduled_on_date(fresh_db):
    """Conflict guard считает только scheduled записи конкретного мастера
    на конкретную дату. Cancelled/completed не считаем (уже не блокируют слот)."""
    m = await create_master(None, "Анна")
    db = await get_db()

    # Пусто — 0
    assert await count_master_scheduled_on_date(m, "2099-05-01") == 0

    # scheduled-запись
    await db.execute(
        """INSERT INTO appointments
           (user_id, name, phone, service_id, service_name, service_duration,
            service_price, date, time, status, master_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', ?)""",
        (1, "X", "+9989", 1, "Маникюр", 60, 100000, "2099-05-01", "10:00", m),
    )
    # cancelled-запись — не считается
    await db.execute(
        """INSERT INTO appointments
           (user_id, name, phone, service_id, service_name, service_duration,
            service_price, date, time, status, master_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'cancelled', ?)""",
        (1, "Y", "+9989", 1, "Маникюр", 60, 100000, "2099-05-01", "12:00", m),
    )
    # запись другого мастера — не считается
    m2 = await create_master(None, "Белла")
    await db.execute(
        """INSERT INTO appointments
           (user_id, name, phone, service_id, service_name, service_duration,
            service_price, date, time, status, master_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', ?)""",
        (1, "Z", "+9989", 1, "Маникюр", 60, 100000, "2099-05-01", "14:00", m2),
    )
    await db.commit()

    assert await count_master_scheduled_on_date(m, "2099-05-01") == 1
    assert await count_master_scheduled_on_date(m, "2099-05-02") == 0
    assert await count_master_scheduled_on_date(m2, "2099-05-01") == 1
