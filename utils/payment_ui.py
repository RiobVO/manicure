"""
UI-хелперы для отображения платёжного статуса записи в админ-карточке
и уведомлениях. Вынесено отдельно чтобы не дублировать логику в
admin_appointments/admin_clients/client_history.
"""
from __future__ import annotations

import logging
from typing import Mapping

from config import PAYMENT_PROVIDER

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
    Отдать ссылку на оплату для повторного показа кнопки «Оплатить».
    Нужно когда клиент случайно ушёл с confirm-сообщения и возвращается
    через «мои записи» — кнопка в карточке должна снова дать ссылку.

    Возвращает None если запись уже оплачена.

    Приоритет источников:
      1. payment_pay_url из БД (сохранён attach_invoice после create_invoice).
      2. Legacy PAYMENT_URL из .env — детерминированный fallback, если
         провайдер упал при записи (create_invoice timeout / mock не запущен),
         но у оператора задана запасная ссылка.
      3. Payme — детерминирован: URL собирается из appt_id + amount, API
         не нужен.
      4. Click — без API invoice_id мы URL собрать не можем (Click выдаёт
         свой внутренний invoice_id), поэтому None.
    """
    if appt.get("paid_at"):
        return None

    saved = appt.get("payment_pay_url")
    if saved:
        return saved

    # Fallback: провайдер упал при записи, но есть legacy PAYMENT_URL —
    # из него всегда можно собрать URL по шаблону.
    from config import PAYMENT_URL
    if PAYMENT_URL:
        amount = appt.get("service_price", 0)
        appt_id = appt.get("id", 0)
        return (
            PAYMENT_URL
            .replace("{amount}", str(amount))
            .replace("{appt_id}", str(appt_id))
        )

    # Fallback для Payme: URL детерминирован из appt_id + amount.
    provider_name = appt.get("payment_provider")
    if provider_name == "payme" or (not provider_name and _active_provider() == "payme"):
        import base64
        from config import PAYME_MERCHANT_ID, PAYMENT_PUBLIC_URL
        appt_id = appt.get("id")
        amount = appt.get("service_price", 0)
        if not PAYME_MERCHANT_ID or not appt_id:
            return None
        amount_tiyin = int(amount) * 100
        return_url = f"{PAYMENT_PUBLIC_URL}/payment/return?appt={appt_id}"
        raw = (
            f"m={PAYME_MERCHANT_ID};"
            f"ac.appointment_id={appt_id};"
            f"a={amount_tiyin};"
            f"c={return_url}"
        )
        return f"https://checkout.paycom.uz/{base64.b64encode(raw.encode()).decode()}"

    return None


def _active_provider() -> str:
    from config import PAYMENT_PROVIDER
    return PAYMENT_PROVIDER
