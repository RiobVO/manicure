"""
Payme Merchant API (JSON-RPC). Phase 1 v.4.

Docs: https://developer.help.paycom.uz/
Auth: Authorization: Basic base64("Paycom:" + SECRET_KEY).
В JSON-RPC body нет подписи — Basic auth единственная защита.

MVP: помечаем paid только на PerformTransaction. CheckPerformTransaction
и CreateTransaction валидируют appointment_id и сумму перед allow'ом —
без этого Payme принимает оплату за несуществующий appt_id (клиент
заплатил бы в никуда). Остальные методы (Cancel/CheckTransaction/
GetStatement) отвечают шаблонным ack. Полная семантика (частичный
рефанд, trans state-machine) — FUTURE.

Payme error codes (из docs):
  -31050  «Неверный код заказа»   — appt_id не найден
  -31001  «Неверная сумма»        — amount ≠ service_price × 100
  -31008  «Невозможно выполнить»  — запись отменена или уже оплачена
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


class _PaymeError(Exception):
    """
    JSON-RPC ошибка, которую сервер должен вернуть Payme. Payme при такой
    ошибке откажется принять/провести платёж — это защищает нас от оплаты
    в никуда.
    """
    def __init__(self, code: int, message: str, rpc_id: Any):
        self.code = code
        self.message = message
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
        Basic auth → парсинг JSON-RPC → валидация appointment_id и суммы
        (для Check/CreateTransaction/PerformTransaction). Если запись
        не существует или сумма не совпадает — raise _PaymeError, сервер
        вернёт JSON-RPC error и Payme откажется провести платёж.

        Возвращает appt_id строкой — только для PerformTransaction.
        Для остальных методов raise _PaymeNonPerform (allow-path).
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
        params = body.get("params") or {}
        rpc_id = body.get("id")

        # Методы, для которых Payme шлёт account.appointment_id — мы должны
        # его провалидировать. Check/Create/Perform — три стадии одного
        # платёжного ивента. Cancel/CheckTransaction/GetStatement — работают
        # по Payme's transaction id, не по нашему appt_id; их валидация в
        # FUTURE (см. докстринг модуля).
        if method in ("CheckPerformTransaction", "CreateTransaction", "PerformTransaction"):
            account = params.get("account", {}) if isinstance(params, dict) else {}
            appt_id_raw = str(account.get("appointment_id", ""))
            if not appt_id_raw or not appt_id_raw.isdigit():
                raise _PaymeError(-31050, "appointment_id invalid", rpc_id)
            appt_id_int = int(appt_id_raw)

            # Ленивая загрузка — избегаем циркулярных импортов и трогаем БД
            # только когда пришёл реальный платёжный запрос.
            from db.payments import get_payment_state
            state = await get_payment_state(appt_id_int)
            if state is None:
                raise _PaymeError(-31050, "appointment not found", rpc_id)

            # Сумма из Payme — в тийинах, service_price — в сумах.
            amount_tiyin = params.get("amount")
            expected_tiyin = int(state["service_price"]) * 100
            if amount_tiyin != expected_tiyin:
                raise _PaymeError(-31001, "amount mismatch", rpc_id)

            if method == "PerformTransaction":
                return appt_id_raw
            # Check/Create — валидация прошла, отдаём allow-path.
            raise _PaymeNonPerform(method=method, params=params, rpc_id=rpc_id)

        # Прочие методы (Cancel/CheckTransaction/GetStatement) — шаблонный ack.
        raise _PaymeNonPerform(
            method=method or "", params=params, rpc_id=rpc_id,
        )
