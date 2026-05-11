"""Фабрика платёжных провайдеров по PAYMENT_PROVIDER из .env."""
from __future__ import annotations

import logging

from config import PAYMENT_PROVIDER
from utils.payments.base import Invoice, PaymentProvider

logger = logging.getLogger(__name__)

_provider: PaymentProvider | None = None


def get_provider() -> PaymentProvider | None:
    """
    Ленивая инициализация провайдера. None → платежи выключены
    (PAYMENT_PROVIDER=none), хендлер падает на legacy PAYMENT_URL.
    """
    global _provider
    if _provider is not None:
        return _provider
    if PAYMENT_PROVIDER == "click":
        from utils.payments.click import ClickProvider
        _provider = ClickProvider()
    elif PAYMENT_PROVIDER == "payme":
        from utils.payments.payme import PaymeProvider
        _provider = PaymeProvider()
    else:
        return None
    logger.info("Payments: провайдер=%s", PAYMENT_PROVIDER)
    return _provider


def _reset_for_tests() -> None:
    """Только для unit-тестов: сброс кеша фабрики, чтобы monkeypatch env сработал."""
    global _provider
    _provider = None


__all__ = ["Invoice", "PaymentProvider", "get_provider"]
