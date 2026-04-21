"""
DB-операции для платежей (Phase 1 v.4).

Один вход на запись — mark_paid(). Идемпотентность: UNIQUE(payment_invoice_id)
на уровне индекса + явная проверка paid_at IS NULL в UPDATE. Повторный webhook
(провайдеры ретраят при 5xx) не переписывает paid_at второй раз.
"""
from __future__ import annotations

import logging
from typing import Any

import aiosqlite

from db.connection import get_db, get_write_lock

logger = logging.getLogger(__name__)


async def attach_invoice(appt_id: int, provider: str, invoice_id: str) -> bool:
    """
    Привязать invoice_id к записи ПЕРЕД редиректом клиента на оплату.

    Возвращает True если привязка прошла, False если у записи уже есть
    invoice — повторный клик по кнопке «Оплатить» отдаёт тот же URL,
    новый invoice не создаём.
    """
    lock = await get_write_lock()
    async with lock:
        db = await get_db()
        try:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT payment_invoice_id FROM appointments WHERE id = ?",
                (appt_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                await db.execute("ROLLBACK")
                raise ValueError(f"appointment {appt_id} not found")
            if row[0]:
                # Клиент повторно нажал «Оплатить» — у записи уже есть invoice.
                await db.execute("ROLLBACK")
                return False
            await db.execute(
                "UPDATE appointments SET payment_provider = ?, payment_invoice_id = ? WHERE id = ?",
                (provider, invoice_id, appt_id),
            )
            await db.execute("COMMIT")
            return True
        except Exception:
            try:
                await db.execute("ROLLBACK")
            except Exception:
                pass
            raise


async def mark_paid(provider: str, invoice_id: str) -> int | None:
    """
    Пометить запись оплаченной по (provider, invoice_id).

    Возвращает appt_id при первой успешной пометке, None если:
      • invoice не найден (левый webhook, но подпись прошла — странно, но возможно);
      • paid_at уже был выставлен (дубль-webhook от провайдера).
    """
    lock = await get_write_lock()
    async with lock:
        db = await get_db()
        try:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT id, paid_at FROM appointments "
                "WHERE payment_provider = ? AND payment_invoice_id = ?",
                (provider, invoice_id),
            )
            row = await cursor.fetchone()
            if row is None:
                await db.execute("ROLLBACK")
                logger.warning(
                    "mark_paid: invoice не найден provider=%s invoice=%s",
                    provider, invoice_id,
                )
                return None
            appt_id, already_paid = row
            if already_paid:
                await db.execute("ROLLBACK")
                logger.info(
                    "mark_paid: дубль webhook appt=%s invoice=%s — игнор",
                    appt_id, invoice_id,
                )
                return None
            await db.execute(
                "UPDATE appointments SET paid_at = datetime('now') WHERE id = ?",
                (appt_id,),
            )
            await db.execute("COMMIT")
            return appt_id
        except Exception:
            try:
                await db.execute("ROLLBACK")
            except Exception:
                pass
            raise


async def get_payment_state(appt_id: int) -> dict[str, Any] | None:
    """Прочитать платёжные поля + сумму. None если записи нет."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT paid_at, payment_provider, payment_invoice_id, "
        "       service_price, user_id, name, service_name, date, time "
        "FROM appointments WHERE id = ?",
        (appt_id,),
    )
    cursor.row_factory = aiosqlite.Row
    row = await cursor.fetchone()
    return dict(row) if row else None
