"""Тесты дедупликации напоминаний (sent_reminders)."""
from db import was_reminder_sent, mark_reminder_sent


async def test_was_reminder_sent_false_initially(fresh_db):
    assert await was_reminder_sent(appointment_id=1, reminder_type="24h") is False


async def test_mark_and_was_reminder_sent(fresh_db):
    await mark_reminder_sent(appointment_id=42, reminder_type="24h")
    assert await was_reminder_sent(42, "24h") is True
    # Другой тип — ещё не отправлен
    assert await was_reminder_sent(42, "2h") is False


async def test_mark_reminder_idempotent(fresh_db):
    """
    UNIQUE-дубликат не должен валить приложение.
    Повторный mark логируется в DEBUG и тихо проглатывается.
    """
    await mark_reminder_sent(10, "24h")
    # Второй раз — не падает
    await mark_reminder_sent(10, "24h")
    assert await was_reminder_sent(10, "24h") is True
