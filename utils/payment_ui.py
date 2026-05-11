"""
UI-хелперы для отображения платёжного статуса записи в админ-карточке
и уведомлениях. Вынесено отдельно чтобы не дублировать логику в
admin_appointments/admin_clients/client_history.
"""
from __future__ import annotations

from typing import Mapping

from config import PAYMENT_PROVIDER


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
