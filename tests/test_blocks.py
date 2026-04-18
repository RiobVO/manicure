"""Тесты блокировок: выходные, временные, фильтрация будущих."""
from datetime import date, timedelta

from db import (
    add_day_off,
    add_time_block,
    delete_blocked_slot,
    get_future_blocks,
    get_time_blocks,
    get_day_schedule_for_master,
    create_master,
    is_day_off,
)
from db.connection import get_db


async def test_add_day_off_for_all_masters(fresh_db):
    """master_id=None → затрагивает всех мастеров."""
    m_a = await create_master(None, "Анна")
    m_b = await create_master(None, "Белла")
    await add_day_off("2030-05-10", master_id=None)

    assert await get_day_schedule_for_master(m_a, "2030-05-10") is None
    assert await get_day_schedule_for_master(m_b, "2030-05-10") is None


async def test_add_day_off_for_one_master(fresh_db):
    """master_id=X не влияет на мастера Y."""
    m_a = await create_master(None, "Анна")
    m_b = await create_master(None, "Белла")
    await add_day_off("2030-05-10", master_id=m_a)

    assert await get_day_schedule_for_master(m_a, "2030-05-10") is None
    # У Б день — рабочий
    assert await get_day_schedule_for_master(m_b, "2030-05-10") is not None


async def test_add_time_block_partial_day(fresh_db):
    """
    Частичная блокировка (is_day_off=0) не должна маркировать день как выходной.
    """
    await add_time_block("2030-05-10", "14:00", "16:00")
    # is_day_off строго проверяет флаг, не частичную блокировку
    assert await is_day_off("2030-05-10") is False

    blocks = await get_time_blocks("2030-05-10")
    assert ("14:00", "16:00") in blocks


async def test_delete_blocked_slot_removes_it(fresh_db):
    await add_time_block("2030-05-10", "14:00", "16:00")
    future = await get_future_blocks()
    block_id = next(b["id"] for b in future if b["date"] == "2030-05-10")

    await delete_blocked_slot(block_id)
    after = await get_future_blocks()
    assert not any(b["id"] == block_id for b in after)


async def test_get_future_blocks_filters_past(fresh_db):
    """
    Блокировка в прошлом — не в списке future.
    Берём дату минимум за 2 дня назад, чтобы отсечь разницу TZ между
    локальной датой и date('now') в SQLite (UTC).
    """
    past = (date.today() - timedelta(days=2)).strftime("%Y-%m-%d")
    future_date = (date.today() + timedelta(days=2)).strftime("%Y-%m-%d")

    await add_day_off(past)
    await add_day_off(future_date)

    future = await get_future_blocks()
    dates = {b["date"] for b in future}
    assert future_date in dates
    assert past not in dates
