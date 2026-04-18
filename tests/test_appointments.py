"""Тесты CRUD записей, атомарности create/reschedule, блокировок по master_id."""
import asyncio

import pytest

from db import (
    create_appointment,
    is_slot_free,
    reschedule_appointment,
    cancel_appointment_by_client,
    get_stats,
    get_user_appointments_page,
    count_user_appointments,
    get_appointment_by_id,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────


async def _create(date="2030-05-10", time="14:00", duration=60, master_id=None,
                  user_id=1, name="Тест", phone="+998999999999",
                  service_id=1, service_name="Маникюр", price=100000):
    return await create_appointment(
        user_id=user_id, name=name, phone=phone,
        service_id=service_id, service_name=service_name,
        service_duration=duration, service_price=price,
        date=date, time=time, master_id=master_id,
    )


# ─── CREATE ──────────────────────────────────────────────────────────────────


async def test_create_appointment_success(fresh_db, seed_master):
    master_id = await seed_master("А")
    appt_id = await _create(master_id=master_id)
    assert isinstance(appt_id, int) and appt_id > 0


async def test_create_appointment_raises_on_overlap_same_master(fresh_db, seed_master):
    """
    Пересечение детектируется когда начало новой записи попадает внутрь
    существующего интервала: старт 14:00, новый старт 14:30 → ValueError.
    Случай с равным стартом (14:00 vs 14:00) — см. тест ниже (xfail).
    """
    master_id = await seed_master("А")
    await _create(time="14:00", duration=60, master_id=master_id)
    with pytest.raises(ValueError):
        await _create(time="14:30", duration=60, master_id=master_id, user_id=2)


async def test_create_appointment_raises_on_equal_start_time(fresh_db, seed_master):
    master_id = await seed_master("А")
    await _create(time="14:00", duration=60, master_id=master_id)
    with pytest.raises(ValueError):
        await _create(time="14:00", duration=60, master_id=master_id, user_id=2)


async def test_create_appointment_ok_for_different_masters_same_time(fresh_db, seed_master):
    m_a = await seed_master("А")
    m_b = await seed_master("Б")
    id1 = await _create(master_id=m_a, user_id=1)
    id2 = await _create(master_id=m_b, user_id=2)
    assert id1 != id2 and id1 > 0 and id2 > 0


async def test_create_appointment_ok_same_master_different_time(fresh_db, seed_master):
    m = await seed_master("А")
    id1 = await _create(time="10:00", duration=60, master_id=m)
    id2 = await _create(time="12:00", duration=60, master_id=m, user_id=2)
    assert id1 and id2


async def test_create_appointment_partial_overlap(fresh_db, seed_master):
    """[14:00-15:00] + попытка [14:30-15:30] → ValueError."""
    m = await seed_master("А")
    await _create(time="14:00", duration=60, master_id=m)
    with pytest.raises(ValueError):
        await _create(time="14:30", duration=60, master_id=m, user_id=2)


async def test_create_appointment_no_master_conflicts_with_master(fresh_db, seed_master):
    """
    Запись без мастера (master_id=None) — это fallback на общий ресурс заведения.
    Если на это время уже есть запись к конкретному мастеру, master=None должна
    получить ValueError: система последовательна (get_booked_times(None) тоже
    возвращает ВСЕ записи на дату без фильтра по master_id).
    """
    m_a = await seed_master("А")
    id1 = await _create(time="14:00", master_id=m_a)
    assert id1 > 0
    with pytest.raises(ValueError):
        await _create(time="14:00", master_id=None, user_id=2)


# ─── is_slot_free ────────────────────────────────────────────────────────────


async def test_is_slot_free_true_when_empty(fresh_db, seed_master):
    m = await seed_master("А")
    assert await is_slot_free("2030-05-10", "14:00", 60, master_id=m) is True


async def test_is_slot_free_false_when_booked(fresh_db, seed_master):
    m = await seed_master("А")
    await _create(time="14:00", master_id=m)
    assert await is_slot_free("2030-05-10", "14:30", 60, master_id=m) is False


async def test_is_slot_free_respects_master_id(fresh_db, seed_master):
    """
    У A — запись на 14:00/60мин. Проверяем слот, начинающийся ВНУТРИ интервала
    (14:30), чтобы не наткнуться на баг равного start_time.
    """
    m_a = await seed_master("А")
    m_b = await seed_master("Б")
    await _create(time="14:00", master_id=m_a)
    # У мастера B в это время ничего нет
    assert await is_slot_free("2030-05-10", "14:30", 60, master_id=m_b) is True
    # У A — занято (14:30 внутри 14:00-15:00)
    assert await is_slot_free("2030-05-10", "14:30", 60, master_id=m_a) is False


async def test_is_slot_free_with_exclude_id(fresh_db, seed_master):
    """
    При переносе запись не должна конфликтовать сама с собой.
    Используем пересекающийся, но не равный start-time слот.
    """
    m = await seed_master("А")
    appt_id = await _create(time="14:00", master_id=m, duration=60)
    # Без exclude — слот 14:30 занят (пересечение с 14:00-15:00)
    assert await is_slot_free("2030-05-10", "14:30", 60, master_id=m) is False
    # С exclude_id — слот свободен
    assert await is_slot_free(
        "2030-05-10", "14:30", 60, master_id=m, exclude_id=appt_id
    ) is True


# ─── RESCHEDULE ──────────────────────────────────────────────────────────────


async def test_reschedule_appointment_success(fresh_db, seed_master):
    m = await seed_master("А")
    appt_id = await _create(time="14:00", master_id=m, duration=60)
    await reschedule_appointment(
        appt_id, new_date="2030-05-11", new_time="15:00",
        service_duration=60, master_id=m,
    )
    appt = await get_appointment_by_id(appt_id)
    assert appt["date"] == "2030-05-11"
    assert appt["time"] == "15:00"


async def test_reschedule_appointment_raises_on_conflict(fresh_db, seed_master):
    """
    Перенос внутрь существующего интервала должен падать.
    (Равный start-time — см. баг выше; здесь проверяем корректный случай.)
    """
    m = await seed_master("А")
    id1 = await _create(time="14:00", master_id=m, duration=60)
    id2 = await _create(time="16:00", master_id=m, duration=60, user_id=2)
    with pytest.raises(ValueError):
        # Переносим id2 на 14:30 — внутри 14:00-15:00
        await reschedule_appointment(
            id2, new_date="2030-05-10", new_time="14:30",
            service_duration=60, master_id=m,
        )


async def test_reschedule_appointment_no_self_conflict(fresh_db, seed_master):
    """
    Перенос записи на её же date/time не должен падать (exclude_id работает).
    Кейс: клиент «переносит» на то же время после каких-то действий.
    """
    m = await seed_master("А")
    appt_id = await _create(time="14:00", master_id=m, duration=60)
    await reschedule_appointment(
        appt_id, new_date="2030-05-10", new_time="14:00",
        service_duration=60, master_id=m,
    )
    # Просто не должно бросить ValueError.
    appt = await get_appointment_by_id(appt_id)
    assert appt["time"] == "14:00"


# ─── CANCEL ──────────────────────────────────────────────────────────────────


async def test_cancel_appointment_by_client_ok(fresh_db, seed_master):
    m = await seed_master("А")
    appt_id = await _create(user_id=42, master_id=m)
    result = await cancel_appointment_by_client(appt_id, user_id=42, reason="планы")
    assert result is True
    appt = await get_appointment_by_id(appt_id)
    assert appt["status"] == "cancelled"
    assert appt["client_cancelled"] == 1


async def test_cancel_appointment_by_client_wrong_user(fresh_db, seed_master):
    m = await seed_master("А")
    appt_id = await _create(user_id=42, master_id=m)
    result = await cancel_appointment_by_client(appt_id, user_id=999)
    assert result is False
    appt = await get_appointment_by_id(appt_id)
    assert appt["status"] == "scheduled"


# ─── STATS ───────────────────────────────────────────────────────────────────


async def test_get_stats_empty_db(fresh_db):
    """Пустая БД → всё по нулям, avg_check=0, без делений на ноль."""
    stats = await get_stats()
    assert stats["today_count"] == 0
    assert stats["completed_count"] == 0
    assert stats["avg_check"] == 0
    assert stats["returning_clients"] == 0
    assert stats["conversion"] == 0


async def test_get_stats_with_data(fresh_db, seed_master):
    m = await seed_master("А")
    await _create(master_id=m, price=100000)
    stats = await get_stats()
    assert "today_count" in stats
    assert "total_revenue" in stats
    assert "top_service_name" in stats


# ─── PAGINATION ──────────────────────────────────────────────────────────────


async def test_get_user_appointments_page_pagination(fresh_db, seed_master):
    m = await seed_master("А")
    user_id = 777
    # 7 записей в разные часы
    for i in range(7):
        await _create(
            user_id=user_id,
            date="2030-05-10",
            time=f"{10 + i:02d}:00",
            master_id=m,
        )
    assert await count_user_appointments(user_id) == 7

    page0 = await get_user_appointments_page(user_id, page=0, per_page=5)
    page1 = await get_user_appointments_page(user_id, page=1, per_page=5)
    assert len(page0) == 5
    assert len(page1) == 2
    # Пересечения страниц нет
    ids0 = {r["id"] for r in page0}
    ids1 = {r["id"] for r in page1}
    assert ids0.isdisjoint(ids1)


# ─── CONCURRENT CREATE ───────────────────────────────────────────────────────


async def test_concurrent_create_appointments_only_one_wins(fresh_db, seed_master):
    """
    Пять параллельных create_appointment на один и тот же слот.
    Lock + симметричный overlap-чек: одна запись создаётся, остальные ловят ValueError.
    """
    m = await seed_master("А")
    results = await asyncio.gather(
        *[
            _create(time="14:00", master_id=m, user_id=100 + i)
            for i in range(5)
        ],
        return_exceptions=True,
    )
    successes = [r for r in results if isinstance(r, int)]
    failures = [r for r in results if isinstance(r, ValueError)]
    assert len(successes) == 1
    assert len(failures) == 4
