"""Базовый провайдер онлайн-оплат (Phase 1 v.4)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Invoice:
    """Результат создания инвойса у провайдера."""
    invoice_id: str      # уникальный id у провайдера (идемпотентность-ключ)
    pay_url: str         # deeplink / страница, куда редиректить клиента


class PaymentProvider(ABC):
    """
    Контракт провайдера оплат.

    create_invoice — HTTP-запрос к провайдеру (Click) или формирование
    base64-деплинка (Payme). Возвращает Invoice для сохранения в appointment.

    verify_and_parse — проверка подписи webhook'а + извлечение invoice_id.
    PermissionError → HTTP 401 (left fail-closed). ValueError → HTTP 400.
    """

    name: str  # "click" | "payme"

    @abstractmethod
    async def create_invoice(self, appt_id: int, amount_uzs: int, phone: str) -> Invoice:
        ...

    @abstractmethod
    async def verify_and_parse(self, headers: dict, raw_body: bytes) -> str:
        """Вернуть invoice_id, если webhook валиден. Иначе — исключение."""
        ...
