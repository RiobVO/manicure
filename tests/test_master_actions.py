"""Тесты v.3 Phase 2: мастер отменяет/переносит свои записи.

Покрытие — шаблоны notify_client (новые event_type) и
reschedule_appointment с master_id (guard от пересечений в FSM мастера).

Сами хендлеры мастера интегрируют эти примитивы, но тестировать их через
моки TG-клиента сейчас не стоит — интеграционный полный прогон пользователь
делает руками.
"""
import pytest

from db import (
    create_appointment,
    create_master,
    get_appointment_by_id,
    reschedule_appointment,
)
from utils.notifications import _CLIENT_TEMPLATES


# ─── Шаблоны уведомлений клиенту ─────────────────────────────────────────────


def test_cancelled_by_master_template_has_all_fields():
    """Сообщение об отмене собирается без KeyError и содержит все
    подставленные значения. Падение format'а = молчаливый fail в проде."""
    tmpl = _CLIENT_TEMPLATES["cancelled_by_master"]
    text = tmpl.format(
        master_name="Оля",
        date="2099-04-25",
        time="14:00",
        service_name="Маникюр классический",
    )
    for fragment in ("Оля", "2099-04-25", "14:00", "Маникюр классический"):
        assert fragment in text, f"Не нашёл {fragment!r} в шаблоне cancelled_by_master"


def test_rescheduled_by_master_template_has_all_fields():
    """Сообщение о переносе: и старая дата/время, и новая — всё в тексте."""
    tmpl = _CLIENT_TEMPLATES["rescheduled_by_master"]
    text = tmpl.format(
        master_name="Оля",
        old_date="2099-04-25", old_time="14:00",
        date="2099-04-26", time="15:00",
        service_name="Педикюр",
    )
    for fragment in (
        "Оля", "2099-04-25", "14:00", "2099-04-26", "15:00", "Педикюр",
    ):
        assert fragment in text, f"Не нашёл {fragment!r} в шаблоне rescheduled_by_master"


def test_cancelled_by_master_missing_key_raises():
    """Защита: если в хендлере забудут передать master_name — KeyError
    сразу, а не тихий мусор в сообщении клиенту."""
    tmpl = _CLIENT_TEMPLATES["cancelled_by_master"]
    with pytest.raises(KeyError):
        tmpl.format(date="2099-04-25", time="14:00", service_name="X")


# ─── reschedule_appointment сохраняет master_id и проверяет пересечения ──────


async def test_master_reschedule_moves_own_appointment(fresh_db):
    """Мастер переносит свою запись — time и date обновляются."""
    m = await create_master(None, "Оля")
    appt_id = await create_appointment(
        user_id=1, name="Аида", phone="+998",
        service_id=1, service_name="Маникюр",
        service_duration=60, service_price=100000,
        date="2099-06-01", time="10:00", master_id=m,
    )

    await reschedule_appointment(
        appt_id, "2099-06-02", "11:00",
        service_duration=60, master_id=m,
    )

    fresh = await get_appointment_by_id(appt_id)
    assert fresh["date"] == "2099-06-02"
    assert fresh["time"] == "11:00"
    assert fresh["status"] == "scheduled"
    assert fresh["master_id"] == m


async def test_master_reschedule_blocks_on_own_overlap(fresh_db):
    """Если в новое время у этого же мастера уже стоит другая запись —
    ValueError, исходная не меняется. Это защита от race в FSM переноса."""
    m = await create_master(None, "Оля")
    # Фоновая запись, которая займёт новое время.
    await create_appointment(
        user_id=1, name="Другой клиент", phone="+998",
        service_id=1, service_name="Маникюр",
        service_duration=60, service_price=100000,
        date="2099-06-02", time="11:00", master_id=m,
    )
    # Переносимая запись.
    appt_id = await create_appointment(
        user_id=2, name="Аида", phone="+998",
        service_id=1, service_name="Маникюр",
        service_duration=60, service_price=100000,
        date="2099-06-01", time="10:00", master_id=m,
    )

    with pytest.raises(ValueError):
        await reschedule_appointment(
            appt_id, "2099-06-02", "11:00",
            service_duration=60, master_id=m,
        )

    # Исходная запись не тронута
    fresh = await get_appointment_by_id(appt_id)
    assert fresh["date"] == "2099-06-01"
    assert fresh["time"] == "10:00"


async def test_master_reschedule_ignores_other_master_occupancy(fresh_db):
    """Запись ДРУГОГО мастера в то же время не блокирует перенос —
    разные мастера работают параллельно, их слоты независимы."""
    m_a = await create_master(None, "Оля")
    m_b = await create_master(None, "Аня")
    # Чужой мастер (m_b) занял 2099-06-02 11:00
    await create_appointment(
        user_id=1, name="Чужой клиент", phone="+998",
        service_id=1, service_name="Маникюр",
        service_duration=60, service_price=100000,
        date="2099-06-02", time="11:00", master_id=m_b,
    )
    # Оля переносит свою запись на то же время — должно пройти.
    appt_id = await create_appointment(
        user_id=2, name="Аида", phone="+998",
        service_id=1, service_name="Маникюр",
        service_duration=60, service_price=100000,
        date="2099-06-01", time="10:00", master_id=m_a,
    )
    await reschedule_appointment(
        appt_id, "2099-06-02", "11:00",
        service_duration=60, master_id=m_a,
    )
    fresh = await get_appointment_by_id(appt_id)
    assert fresh["time"] == "11:00"
