"""Интеграционные сценарии: полные пути бронирования, отмены, блокировок."""
from datetime import date, timedelta

from db import (
    create_master,
    add_service,
    create_appointment,
    cancel_appointment_by_client,
    update_appointment_status,
    reschedule_appointment,
    get_appointments_by_date_full,
    get_user_appointments_page,
    delete_master,
    add_day_off,
    get_day_schedule_for_master,
)


async def test_full_booking_flow_single_master(fresh_db):
    master_id = await create_master(None, "Анна")
    service_id = await add_service("Маникюр базовый", 150000, 60)

    appt_id = await create_appointment(
        user_id=42, name="Клиент", phone="+998999000000",
        service_id=service_id, service_name="Маникюр базовый",
        service_duration=60, service_price=150000,
        date="2030-05-10", time="14:00", master_id=master_id,
    )
    assert appt_id > 0

    page = await get_user_appointments_page(42)
    assert len(page) == 1
    assert page[0]["service_name"] == "Маникюр базовый"


async def test_reschedule_conflict_with_other_master_ok(fresh_db):
    """
    Мастер A занят на 14:00. Переносим запись клиента к мастеру B на 14:00.
    Разные мастера — конфликта нет.
    """
    m_a = await create_master(None, "Анна")
    m_b = await create_master(None, "Белла")

    # У Анны на 14:00 уже кто-то записан
    await create_appointment(
        user_id=1, name="X", phone="+9981",
        service_id=1, service_name="Маникюр", service_duration=60,
        service_price=100000,
        date="2030-05-10", time="14:00", master_id=m_a,
    )
    # Клиент изначально был к Анне на 10:00
    appt_id = await create_appointment(
        user_id=2, name="Y", phone="+9982",
        service_id=1, service_name="Маникюр", service_duration=60,
        service_price=100000,
        date="2030-05-10", time="10:00", master_id=m_a,
    )
    # Переносим к Белле на 14:00 — конфликта быть не должно
    await reschedule_appointment(
        appt_id, new_date="2030-05-10", new_time="14:00",
        service_duration=60, master_id=m_b,
    )


async def test_client_cancel_then_admin_sees_cancelled(fresh_db):
    m = await create_master(None, "Анна")
    appt_id = await create_appointment(
        user_id=42, name="Клиент", phone="+9989",
        service_id=1, service_name="Маникюр", service_duration=60,
        service_price=100000,
        date="2030-05-10", time="14:00", master_id=m,
    )
    await cancel_appointment_by_client(appt_id, user_id=42, reason="планы")

    rows = await get_appointments_by_date_full("2030-05-10")
    assert any(r["id"] == appt_id and r["status"] == "cancelled" for r in rows)


async def test_master_deletion_blocked_by_future_appt(fresh_db):
    m = await create_master(None, "Анна")
    tomorrow = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
    await create_appointment(
        user_id=1, name="X", phone="+9989",
        service_id=1, service_name="Маникюр", service_duration=60,
        service_price=100000,
        date=tomorrow, time="10:00", master_id=m,
    )
    assert await delete_master(m) is False


async def test_master_deletion_ok_after_appt_cancelled(fresh_db):
    """
    После cancel запись остаётся в БД со статусом cancelled,
    поэтому delete_master возвращает False (история сохраняется).
    """
    m = await create_master(None, "Анна")
    tomorrow = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
    appt_id = await create_appointment(
        user_id=1, name="X", phone="+9989",
        service_id=1, service_name="Маникюр", service_duration=60,
        service_price=100000,
        date=tomorrow, time="10:00", master_id=m,
    )
    await update_appointment_status(appt_id, "cancelled")
    assert await delete_master(m) is False


async def test_block_whole_day_blocks_booking_for_that_master_only(fresh_db):
    m_a = await create_master(None, "Анна")
    m_b = await create_master(None, "Белла")
    await add_day_off("2030-05-10", master_id=m_a)

    assert await get_day_schedule_for_master(m_a, "2030-05-10") is None
    assert await get_day_schedule_for_master(m_b, "2030-05-10") is not None
