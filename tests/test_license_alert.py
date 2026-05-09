"""Тесты проактивного алерта об истечении лицензии (scheduler._should_alert_license).

Покрываем чистую функцию решения «слать или нет» — без файлов, без сети, без бота.
Реальная отправка в TG тестируется руками через временную лицензию (см. LICENSING.md).
"""
from datetime import datetime, timedelta, timezone

from scheduler import LICENSE_ALERT_DAYS_BEFORE, _should_alert_license
from utils.license import License, LicenseMode, LicenseState


def _state_with_expires_in(days: int) -> LicenseState:
    """Построить LicenseState с expires_at = now + days. Остальные поля
    заглушки — не используются в _should_alert_license."""
    now = datetime.now(timezone.utc)
    lic = License(
        tenant_slug="test",
        customer_name="Test Salon",
        license_id="test-id",
        issued_at=now - timedelta(days=30),
        expires_at=now + timedelta(days=days),
    )
    return LicenseState(mode=LicenseMode.OK, license=lic)


def test_no_alert_when_no_license():
    """DEV-режим / нет ключа → license=None → не слать."""
    state = LicenseState(mode=LicenseMode.DEV, license=None)
    should, days = _should_alert_license(state, datetime.now(timezone.utc))
    assert should is False
    assert days == 0


def test_no_alert_when_far_from_expiry():
    """Лицензия на год вперёд — ничего не делаем."""
    state = _state_with_expires_in(days=365)
    should, _ = _should_alert_license(state, datetime.now(timezone.utc))
    assert should is False


def test_alert_when_within_window():
    """Остался 30 дней — слать (30 ≤ 60)."""
    state = _state_with_expires_in(days=30)
    should, days = _should_alert_license(state, datetime.now(timezone.utc))
    assert should is True
    assert 29 <= days <= 30  # суточная погрешность timedelta.days


def test_alert_at_window_edge():
    """Ровно на границе 60 дней — слать (оператор <=)."""
    state = _state_with_expires_in(days=60)
    should, days = _should_alert_license(state, datetime.now(timezone.utc))
    assert should is True
    assert days <= LICENSE_ALERT_DAYS_BEFORE


def test_no_alert_when_already_expired():
    """Лицензия уже истекла — за это отвечает _warn_grace на старте, не этот
    alerting-loop. days_left <= 0 → не слать, чтобы не дублировать."""
    state = _state_with_expires_in(days=-5)
    should, _ = _should_alert_license(state, datetime.now(timezone.utc))
    assert should is False


def test_no_alert_when_far_negative():
    """Лицензия истекла сильно давно (grace кончился) — тоже не шлём:
    пользователь уже либо в restricted, либо enforcement off. Не наша задача."""
    state = _state_with_expires_in(days=-200)
    should, _ = _should_alert_license(state, datetime.now(timezone.utc))
    assert should is False
