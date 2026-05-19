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


async def resolve_pay_url(appt: Mapping) -> str | None:
    """
    Async-версия reconstruct_pay_url с retry через provider.create_invoice.

    Зачем: если в момент подтверждения записи провайдер был недоступен
    (Click API down, mock не запущен, сеть моргнула), payment_pay_url в
    БД остался NULL. Клиент открывает «Мои записи» и не видит кнопку
    оплаты — запись-«зомби». Retry при просмотре восстанавливает ссылку:
    один раз дёргаем API, сохраняем pay_url в БД, дальше работает как
    обычно из кеша.

    Порядок попыток:
      1. paid_at → None (уже оплачено, кнопка не нужна).
      2. payment_pay_url из БД → вернуть его (happy path).
      3. PAYMENT_URL legacy fallback → собрать из шаблона.
      4. Payme detereministic — URL собирается без API.
      5. Click / другой провайдер — попытка create_invoice + attach_invoice.
         Ошибку глотаем (provider всё ещё может быть недоступен),
         возвращаем None.
    """
    if appt.get("paid_at"):
        return None

    saved = appt.get("payment_pay_url")
    if saved:
        return saved

    # Сначала пробуем синхронные пути (legacy PAYMENT_URL + Payme детерминизм)
    # — они не делают сеть, быстрые.
    sync_url = reconstruct_pay_url(appt)
    if sync_url:
        return sync_url

    # Осталась одна причина: Click без сохранённого URL. Ретраим create_invoice.
    if appt.get("status") != "scheduled":
        return None

    appt_id = appt.get("id")
    amount = appt.get("service_price")
    phone = appt.get("phone")
    if not (appt_id and amount and phone):
        return None

    from utils.payments import get_provider
    provider = get_provider()
    if provider is None:
        return None

    try:
        invoice = await provider.create_invoice(
            appt_id=appt_id, amount_uzs=int(amount), phone=str(phone),
        )
    except Exception as exc:
        logger.warning(
            "resolve_pay_url retry create_invoice упал appt=%s: %s",
            appt_id, exc,
        )
        return None

    # Сохраняем чтобы в следующий раз читали из БД без API-запроса.
    # attach_invoice вернёт False если invoice_id уже есть — в сиротских
    # записях он NULL, так что должен пройти. На False просто вернём URL:
    # клиент оплатит, провайдер пришлёт webhook по нашему же appt_id.
    try:
        from db.payments import attach_invoice
        await attach_invoice(
            appt_id, provider.name, invoice.invoice_id, invoice.pay_url,
        )
    except Exception:
        logger.warning(
            "resolve_pay_url: attach_invoice не записал appt=%s — URL отдаём,"
            " но в следующий раз снова дёрнем API",
            appt_id, exc_info=True,
        )

    return invoice.pay_url
