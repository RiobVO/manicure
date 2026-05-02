"""Тесты логики мастеров: создание, расписание, блокировки, удаление."""
from db import (
    create_master,
    get_active_masters,
    get_all_masters,
    toggle_master_active,
    get_master_schedule,
    get_day_schedule_for_master,
    get_time_blocks_for_master,
    delete_master,
    add_day_off,
    add_time_block,
    update_weekday_schedule,
    create_appointment,
    update_appointment_status,
    get_all_masters_ratings,
)
from db.connection import get_db


async def test_create_master_seeds_schedule(fresh_db):
    """После create_master в master_schedule должны появиться все 7 дней."""
    master_id = await create_master(user_id=None, name="Анна")
    schedule = await get_master_schedule(master_id)
    assert set(schedule.keys()) == {0, 1, 2, 3, 4, 5, 6}
    for wd, hours in schedule.items():
        assert "work_start" in hours
        assert "work_end" in hours


async def test_get_active_masters_filters_inactive(fresh_db):
    m_a = await create_master(None, "Анна")
    m_b = await create_master(None, "Белла")
    await toggle_master_active(m_b)  # делаем неактивной
    active = await get_active_masters()
    active_ids = {m["id"] for m in active}
    assert m_a in active_ids
    assert m_b not in active_ids


async def test_get_day_schedule_for_master_returns_hours(fresh_db):
    master_id = await create_master(None, "Анна")
    # Дефолт weekly_schedule: 9..19
    # 2030-05-10 — пятница (weekday=4). Берём дату с рабочими часами.
    result = await get_day_schedule_for_master(master_id, "2030-05-10")
    assert result is not None
    start, end = result
    assert start == 9
    assert end == 19


async def test_get_day_schedule_for_master_returns_none_on_global_day_off(fresh_db):
    """Выходной в weekly_schedule (work_start=NULL) → None для мастера."""
    master_id = await create_master(None, "Анна")
    # 2030-05-11 — суббота (weekday=5). Помечаем как выходной глобально.
    await update_weekday_schedule(weekday=5, work_start=None, work_end=None)
    # Также обновим master_schedule для этого мастера, т.к. seed скопировал старые часы.
    db = await get_db()
    await db.execute(
        "UPDATE master_schedule SET work_start = NULL, work_end = NULL "
        "WHERE master_id = ? AND weekday = 5",
        (master_id,),
    )
    await db.commit()
    assert await get_day_schedule_for_master(master_id, "2030-05-11") is None


async def test_get_day_schedule_for_master_returns_none_on_blocked_day_master(fresh_db):
    master_id = await create_master(None, "Анна")
    await add_day_off(date="2030-05-10", reason="отпуск", master_id=master_id)
    assert await get_day_schedule_for_master(master_id, "2030-05-10") is None


async def test_get_day_schedule_for_master_returns_none_on_blocked_day_global(fresh_db):
    """add_day_off с master_id=None должен блокировать любого мастера."""
    m_a = await create_master(None, "Анна")
    m_b = await create_master(None, "Белла")
    await add_day_off(date="2030-05-10", reason="санобработка", master_id=None)
    assert await get_day_schedule_for_master(m_a, "2030-05-10") is None
    assert await get_day_schedule_for_master(m_b, "2030-05-10") is None


async def test_get_day_schedule_for_master_unaffected_by_other_master_block(fresh_db):
    m_a = await create_master(None, "Анна")
    m_b = await create_master(None, "Белла")
    await add_day_off(date="2030-05-10", master_id=m_b)
    # А всё ещё работает
    assert await get_day_schedule_for_master(m_a, "2030-05-10") is not None
    # Б — нет
    assert await get_day_schedule_for_master(m_b, "2030-05-10") is None


async def test_get_time_blocks_for_master_includes_global_blocks(fresh_db):
    m = await create_master(None, "Анна")
    await add_time_block("2030-05-10", "14:00", "16:00", master_id=None)
    blocks = await get_time_blocks_for_master(m, "2030-05-10")
    assert ("14:00", "16:00") in blocks


async def test_get_time_blocks_for_master_excludes_other_master(fresh_db):
    m_a = await create_master(None, "Анна")
    m_b = await create_master(None, "Белла")
    await add_time_block("2030-05-10", "14:00", "16:00", master_id=m_b)
    blocks_a = await get_time_blocks_for_master(m_a, "2030-05-10")
    assert ("14:00", "16:00") not in blocks_a


async def test_delete_master_blocked_by_scheduled_appt(fresh_db):
    m = await create_master(None, "Анна")
    # Будущая scheduled запись
    await create_appointment(
        user_id=1, name="X", phone="+9989",
        service_id=1, service_name="Маникюр", service_duration=60,
        service_price=100000,
        date="2099-01-01", time="10:00", master_id=m,
    )
    assert await delete_master(m) is False


async def test_delete_master_ok_when_only_completed(fresh_db):
    """
    Даже completed-запись — это история. delete_master возвращает False,
    чтобы сохранить целостность истории. Мастер деактивируется, а не удаляется.
    """
    m = await create_master(None, "Анна")
    appt_id = await create_appointment(
        user_id=1, name="X", phone="+9989",
        service_id=1, service_name="Маникюр", service_duration=60,
        service_price=100000,
        date="2000-01-01", time="10:00", master_id=m,
    )
    await update_appointment_status(appt_id, "completed")
    assert await delete_master(m) is False


async def test_delete_master_blocked_by_any_history(fresh_db):
    """
    Наличие любой записи (даже completed/cancelled, даже вставленной напрямую)
    блокирует удаление мастера.
    """
    m = await create_master(None, "Анна")
    db = await get_db()
    # Вставляем completed-запись напрямую, минуя create_appointment
    await db.execute(
        """INSERT INTO appointments
           (user_id, name, phone, service_id, service_name, service_duration,
            service_price, date, time, status, master_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?)""",
        (1, "X", "+9989", 1, "Маникюр", 60, 100000, "2000-01-01", "10:00", m),
    )
    await db.commit()
    assert await delete_master(m) is False


async def test_get_all_masters_ratings_shape(fresh_db):
    """Просто проверяем, что функция не падает и возвращает dict."""
    await create_master(None, "Анна")
    ratings = await get_all_masters_ratings()
    assert isinstance(ratings, dict)


async def test_toggle_master_active_switches(fresh_db):
    m = await create_master(None, "Анна")
    all_list = await get_all_masters()
    before = next(x for x in all_list if x["id"] == m)["is_active"]
    assert before == 1

    await toggle_master_active(m)
    all_list = await get_all_masters()
    after = next(x for x in all_list if x["id"] == m)["is_active"]
    assert after == 0

    await toggle_master_active(m)
    all_list = await get_all_masters()
    final = next(x for x in all_list if x["id"] == m)["is_active"]
    assert final == 1
