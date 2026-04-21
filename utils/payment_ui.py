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
    Отдать сохранённый pay_url для повторного показа кнопки «Оплатить».
    Нужно когда клиент случайно ушёл с confirm-сообщения и возвращается
    через «мои записи» — кнопка в карточке должна снова дать ту же ссылку.

    Возвращает None если:
      • запись уже оплачена (paid_at != NULL) — платить нечего;
      • pay_url не сохранён (инвойс не выставлялся или запись до v4).

    URL детерминирован: он был записан в БД при attach_invoice(). Не зовём
    create_invoice повторно — Click создал бы второй инвойс.
    """
    if appt.get("paid_at"):
        return None
    return appt.get("payment_pay_url") or None
