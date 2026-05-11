"""
Payme Merchant API (JSON-RPC). Phase 1 v.4.

Docs: https://developer.help.paycom.uz/
Auth: Authorization: Basic base64("Paycom:" + SECRET_KEY).
В JSON-RPC body нет подписи — Basic auth единственная защита.

MVP: помечаем paid только на PerformTransaction. Остальные методы
(CheckPerformTransaction / CreateTransaction / Cancel / CheckTransaction)
обрабатываются в server.py шаблонным ack — этого хватает для принятия
денег. Полная семантика (проверка дублей, частичный рефанд) — FUTURE.
"""
from __future__ import annotations

import base64
import hmac
import json
import logging
from typing import Any

from config import PAYME_MERCHANT_ID, PAYME_SECRET_KEY, PAYMENT_PUBLIC_URL
from utils.payments.base import Invoice, PaymentProvider

logger = logging.getLogger(__name__)


class _PaymeNonPerform(Exception):
    """Не-PerformTransaction метод — сервер отвечает ack, paid не ставим."""
    def __init__(self, method: str, params: dict[str, Any], rpc_id: Any):
        self.method = method
        self.params = params
        self.rpc_id = rpc_id


class PaymeProvider(PaymentProvider):
    name = "payme"

    async def create_invoice(self, appt_id: int, amount_uzs: int, phone: str) -> Invoice:
        """
        У Payme нет отдельного invoice/create — клиент идёт на checkout.paycom.uz
        с base64-кодированными параметрами, Payme после оплаты сам шлёт нам
        PerformTransaction. invoice_id = str(appt_id): наш primary key
        хранится в params.account.appointment_id.
        """
        amount_tiyin = amount_uzs * 100  # Payme работает в тийинах
        return_url = f"{PAYMENT_PUBLIC_URL}/payment/return?appt={appt_id}"
        raw = (
            f"m={PAYME_MERCHANT_ID};"
            f"ac.appointment_id={appt_id};"
            f"a={amount_tiyin};"
            f"c={return_url}"
        )
        payload_b64 = base64.b64encode(raw.encode()).decode()
        pay_url = f"https://checkout.paycom.uz/{payload_b64}"
        return Invoice(invoice_id=str(appt_id), pay_url=pay_url)

    async def verify_and_parse(self, headers: dict, raw_body: bytes) -> str:
        """
        Проверка Basic auth + извлечение appointment_id из params.account.
        Не-Perform методы вылетают через _PaymeNonPerform для server.py.
        """
        auth = headers.get("Authorization") or headers.get("authorization") or ""
        expected = "Basic " + base64.b64encode(
            f"Paycom:{PAYME_SECRET_KEY}".encode()
        ).decode()
        if not hmac.compare_digest(auth, expected):
            raise PermissionError("payme: basic auth mismatch")

        try:
            body = json.loads(raw_body.decode("utf-8"))
        except Exception as exc:
            raise ValueError(f"payme: bad json: {exc}") from exc

        method = body.get("method")
        params = body.get("params", {})
        if method != "PerformTransaction":
            raise _PaymeNonPerform(
                method=method or "", params=params, rpc_id=body.get("id"),
            )

        account = params.get("account", {}) if isinstance(params, dict) else {}
        appt_id = str(account.get("appointment_id", ""))
        if not appt_id:
            raise ValueError("payme: params.account.appointment_id missing")
        return appt_id
