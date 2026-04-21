"""
Click Merchant API (Узбекистан). Phase 1 v.4.

Docs: https://docs.click.uz/click-api-request/
Модель webhook'а двухшаговая: Prepare (action=0) → Complete (action=1).
Подпись — MD5(click_trans_id + service_id + SECRET + merchant_trans_id +
[merchant_prepare_id] + amount + action + sign_time).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from urllib.parse import parse_qs

import aiohttp

from config import (
    CLICK_API_BASE,
    CLICK_MERCHANT_ID,
    CLICK_MERCHANT_USER_ID,
    CLICK_PAY_URL_BASE,
    CLICK_SECRET_KEY,
    CLICK_SERVICE_ID,
)
from utils.payments.base import Invoice, PaymentProvider

logger = logging.getLogger(__name__)


class _ClickPrepare(Exception):
    """
    Сигнал server.py что пришёл Prepare-шаг (action=0). Нужен отдельный
    JSON-ответ с merchant_prepare_id, и запись НЕ помечать paid — финал
    приходит на Complete (action=1).
    """
    def __init__(self, merchant_trans_id: str, click_trans_id: str):
        self.merchant_trans_id = merchant_trans_id
        self.click_trans_id = click_trans_id


class ClickProvider(PaymentProvider):
    name = "click"

    def _auth_header(self) -> str:
        """
        Click Auth header: <merchant_user_id>:<digest>:<timestamp>.
        digest = sha1(timestamp + SECRET_KEY).
        """
        ts = str(int(time.time()))
        digest = hashlib.sha1((ts + CLICK_SECRET_KEY).encode()).hexdigest()
        return f"{CLICK_MERCHANT_USER_ID}:{digest}:{ts}"

    async def create_invoice(self, appt_id: int, amount_uzs: int, phone: str) -> Invoice:
        """
        POST {CLICK_API_BASE}/invoice/create → {error_code, invoice_id, ...}.
        Возвращает invoice_id + готовый pay_url для кнопки в чате.
        """
        payload = {
            "service_id": int(CLICK_SERVICE_ID),
            "amount": float(amount_uzs),
            "phone_number": phone.lstrip("+"),
            "merchant_trans_id": str(appt_id),
        }
        headers = {
            "Accept": "application/json",
            "Auth": self._auth_header(),
            "Content-Type": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{CLICK_API_BASE}/invoice/create", json=payload, headers=headers
            ) as resp:
                data = await resp.json()
        if data.get("error_code", -1) != 0:
            raise RuntimeError(f"Click invoice create failed: {data}")
        invoice_id = str(data["invoice_id"])
        base = CLICK_PAY_URL_BASE or "https://my.click.uz/services/pay"
        pay_url = (
            f"{base}"
            f"?service_id={CLICK_SERVICE_ID}"
            f"&merchant_id={CLICK_MERCHANT_ID}"
            f"&amount={amount_uzs}"
            f"&transaction_param={invoice_id}"
        )
        return Invoice(invoice_id=invoice_id, pay_url=pay_url)

    async def verify_and_parse(self, headers: dict, raw_body: bytes) -> str:
        """
        Верификация webhook'а. Парсим x-www-form-urlencoded вручную —
        канонизация байт должна совпадать с тем, что Click хэширует
        (см. docs: формат подписи строго позиционный).

        Возвращает merchant_trans_id (= наш appt_id) для Complete.
        Бросает _ClickPrepare для Prepare — обработка в server.py.
        """
        parsed = parse_qs(raw_body.decode("utf-8"))

        def _get(k: str) -> str:
            v = parsed.get(k, [""])
            return v[0] if v else ""

        click_trans_id = _get("click_trans_id")
        service_id = _get("service_id")
        merchant_trans_id = _get("merchant_trans_id")
        merchant_prepare_id = _get("merchant_prepare_id")  # пусто на prepare
        amount = _get("amount")
        action = _get("action")
        sign_time = _get("sign_time")
        sign_string = _get("sign_string")

        if not sign_string or len(sign_string) != 32:
            raise PermissionError("click: missing/invalid sign_string")

        raw = (
            f"{click_trans_id}{service_id}{CLICK_SECRET_KEY}{merchant_trans_id}"
            f"{merchant_prepare_id}{amount}{action}{sign_time}"
        )
        expected = hashlib.md5(raw.encode()).hexdigest()

        if not hmac.compare_digest(expected, sign_string):
            raise PermissionError("click: signature mismatch")

        if action == "0":
            # Prepare: говорим «принимаем», но paid не ставим.
            raise _ClickPrepare(
                merchant_trans_id=merchant_trans_id,
                click_trans_id=click_trans_id,
            )
        if action != "1":
            raise ValueError(f"click: unsupported action={action}")

        return merchant_trans_id  # = appt_id (str)
