"""Тесты settings и weekly_schedule."""
from db import (
    get_setting,
    set_setting,
    get_weekly_schedule,
    get_day_schedule,
    update_weekday_schedule,
)


async def test_get_setting_default_when_missing(fresh_db):
    value = await get_setting("nonexistent_key", default="fallback")
    assert value == "fallback"


async def test_set_and_get_setting_roundtrip(fresh_db):
    await set_setting("custom_key", "hello")
    assert await get_setting("custom_key") == "hello"

    # Перезапись — INSERT OR REPLACE
    await set_setting("custom_key", "world")
    assert await get_setting("custom_key") == "world"


async def test_get_weekly_schedule_returns_all_7_days(fresh_db):
    schedule = await get_weekly_schedule()
    assert set(schedule.keys()) == {0, 1, 2, 3, 4, 5, 6}


async def test_update_weekday_schedule_to_day_off(fresh_db):
    """work_start=None делает день выходным."""
    # 2030-05-11 — воскресенье (weekday=6)
    await update_weekday_schedule(weekday=6, work_start=None, work_end=None)
    # 2030-05-11 это Суббота? Проверим явно — берём понедельник на 2030-05-06
    # Вместо зависимости от даты — проверим через get_day_schedule с воскресеньем.
    # 2030-05-12 — воскресенье? Ищем нужную дату для weekday=6.
    # Проще: 2024-01-07 — воскресенье.
    assert await get_day_schedule("2024-01-07") is None


async def test_get_day_schedule_respects_update(fresh_db):
    # 2024-01-08 — понедельник (weekday=0)
    await update_weekday_schedule(weekday=0, work_start=11, work_end=20)
    result = await get_day_schedule("2024-01-08")
    assert result == (11, 20)
