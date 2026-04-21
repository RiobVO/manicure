"""
UI-хелперы для отображения платёжного статуса записи в админ-карточке
и уведомлениях. Вынесено отдельно чтобы не дублировать логику в
admin_appointments/admin_clients/client_history.
"""
from __future__ import annotations

import base64
import logging
from typing import Mapping

from config import (
    CLICK_MERCHANT_ID,
    CLICK_PAY_URL_BASE,
    CLICK_SERVICE_ID,
    PAYME_MERCHANT_ID,
    PAYMENT_PROVIDER,
    PAYMENT_PUBLIC_URL,
)

logger = logging.getLogger(__name__)


def payment_pill(appt: Mapping) -> str:
    """
    Возвращает однострочный pill со статусом оплаты для карточки записи.
    Пустая строка — ничего не показываем (платежи не настроены, инвойса нет).

    Логика:
    - paid_at есть  → 💰 Оплачено
    - invoice есть, paid_at нет → ⏳ Ждёт оплаты
    - invoice нет, PAYMENT_PROVIDER включён → — без оплаты (для старых записей
      до миграции или если клиент не дошёл до confirm_yes, но запись создана вручную)
    - PAYMENT_PROVIDER=none и инвойса никогда не было → пусто
      (legacy-бот не показывает лишний pill)
    """
    paid = appt.get("paid_at") if hasattr(appt, "get") else None
    invoice = appt.get("payment_invoice_id") if hasattr(appt, "get") else None

    if paid:
        return "\n💰 Оплачено"
    if invoice:
        return "\n⏳ Ждёт оплаты"
    if PAYMENT_PROVIDER != "none":
        return "\n— Без оплаты"
    return ""


def reconstruct_pay_url(appt: Mapping) -> str | None:
    """
    Восстановить pay_url для уже созданного инвойса. Нужно когда клиент
    случайно ушёл с сообщения-оплаты и возвращается через «мои записи» —
    кнопка в карточке записи должна снова дать ему ссылку.

    Возвращает None если:
      • провайдер не настроен или none,
      • у записи нет payment_invoice_id (инвойс не выставлялся),
      • запись уже оплачена (paid_at != NULL) — платить нечего.

    Не зовёт провайдер-API: url детерминирован по сохранённым полям.
    Двойной вызов create_invoice у Click создал бы второй инвойс — мы
    этого не хотим.
    """
    if appt.get("paid_at"):
        return None
    invoice_id = appt.get("payment_invoice_id")
    if not invoice_id:
        return None
    provider = appt.get("payment_provider") or PAYMENT_PROVIDER
    amount = appt.get("service_price", 0)

    if provider == "click":
        base = CLICK_PAY_URL_BASE or "https://my.click.uz/services/pay"
        return (
            f"{base}"
            f"?service_id={CLICK_SERVICE_ID}"
            f"&merchant_id={CLICK_MERCHANT_ID}"
            f"&amount={amount}"
            f"&transaction_param={invoice_id}"
        )

    if provider == "payme":
        # invoice_id в Payme = appt_id (см. PaymeProvider.create_invoice).
        appt_id = appt.get("id") or invoice_id
        amount_tiyin = int(amount) * 100
        return_url = f"{PAYMENT_PUBLIC_URL}/payment/return?appt={appt_id}"
        raw = (
            f"m={PAYME_MERCHANT_ID};"
            f"ac.appointment_id={appt_id};"
            f"a={amount_tiyin};"
            f"c={return_url}"
        )
        payload_b64 = base64.b64encode(raw.encode()).decode()
        return f"https://checkout.paycom.uz/{payload_b64}"

    return None
