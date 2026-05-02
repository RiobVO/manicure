"""Тесты generate_free_slots из utils.slots."""
from datetime import datetime, timedelta, timezone

from utils.slots import generate_free_slots


def _future_date(days_ahead: int = 3) -> str:
    """Берём дату в будущем, чтобы обойти ветку 'today' и MIN_BOOKING_ADVANCE_HOURS."""
    return (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")


def test_generate_slots_empty_no_bookings():
    """
    9–18, step 30, duration 60 → слоты c 9:00 до 17:00 включительно — 17 шт.
    Проверяем точный контур: первый 09:00, последний помещается если start+60 <= 18:00.
    """
    slots = generate_free_slots(
        booked=[],
        duration=60,
        date_str=_future_date(),
        work_start=9,
        work_end=18,
        slot_step=30,
        blocked_ranges=[],
    )
    # 9:00..17:00 с шагом 30 мин = 17 слотов
    assert slots[0] == "09:00"
    assert slots[-1] == "17:00"
    assert len(slots) == 17


def test_generate_slots_respects_bookings():
    """Запись [10:00, 60мин] — слоты с 09:30 по 10:30 пропадают."""
    slots = generate_free_slots(
        booked=[("10:00", 60)],
        duration=60,
        date_str=_future_date(),
        work_start=9,
        work_end=18,
        slot_step=30,
    )
    # 09:30+60=10:30 — пересекается с [10:00..11:00] → пропадает
    # 10:00+60=11:00 — пересекается → пропадает
    # 10:30+60=11:30 — пересекается ([10:30..11:30] vs [10:00..11:00]) → пропадает
    # 11:00+60=12:00 — НЕ пересекается с [10:00..11:00] → остаётся
    assert "09:00" in slots
    assert "09:30" not in slots
    assert "10:00" not in slots
    assert "10:30" not in slots
    assert "11:00" in slots


def test_generate_slots_respects_blocked_ranges():
    """Блокировка [13:00-14:00] — слоты, пересекающие этот интервал, пропадают."""
    slots = generate_free_slots(
        booked=[],
        duration=60,
        date_str=_future_date(),
        work_start=9,
        work_end=18,
        slot_step=30,
        blocked_ranges=[("13:00", "14:00")],
    )
    # 12:30+60=13:30 — пересекает → пропадает
    # 13:00+60=14:00 — пересекает → пропадает
    # 13:30+60=14:30 — пересекает ([13:30..14:30] vs [13:00..14:00]) → пропадает
    # 14:00+60=15:00 — НЕ пересекает (slot_start>=bl_end) → остаётся
    assert "12:00" in slots
    assert "12:30" not in slots
    assert "13:00" not in slots
    assert "13:30" not in slots
    assert "14:00" in slots


def test_generate_slots_today_min_advance(monkeypatch):
    """
    Сегодня 14:30. MIN_BOOKING_ADVANCE_HOURS=3 → начало 17:30.
    С шагом 30 — первый слот 17:30. С шагом 60 и duration=60: 17:30 + 60 = 18:30,
    а end_of_day=18:00 → слотов нет. Делаем шаг 30 и work_end 20, duration=60.
    """
    from config import TZ

    today = datetime.now(TZ).date()
    today_str = today.strftime("%Y-%m-%d")

    # Мокаем now_local в handlers.client: сегодня 14:30 локального времени.
    fake_now = datetime.combine(today, datetime.min.time()).replace(
        hour=14, minute=30, tzinfo=TZ
    )

    def fake_now_local():
        return fake_now

    monkeypatch.setattr("utils.slots.now_local", fake_now_local)

    slots = generate_free_slots(
        booked=[],
        duration=60,
        date_str=today_str,
        work_start=9,
        work_end=20,
        slot_step=30,
    )
    # 14:30 + 3h = 17:30 → первый доступный слот именно 17:30
    assert slots, "Ожидались свободные слоты"
    assert slots[0] == "17:30"
    # Слоты до 17:30 не появляются
    for t in slots:
        hh, mm = t.split(":")
        assert int(hh) * 60 + int(mm) >= 17 * 60 + 30


def test_generate_slots_duration_longer_than_day():
    """Длительность 600 мин при рабочем дне 9..18 → слотов нет."""
    slots = generate_free_slots(
        booked=[],
        duration=600,
        date_str=_future_date(),
        work_start=9,
        work_end=18,
        slot_step=30,
    )
    assert slots == []
