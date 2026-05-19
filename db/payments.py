"""
DB-операции для платежей (Phase 1 v.4).

Один вход на запись — mark_paid(). Идемпотентность: UNIQUE(payment_invoice_id)
на уровне индекса + явная проверка paid_at IS NULL в UPDATE. Повторный webhook
(провайдеры ретраят при 5xx) не переписывает paid_at второй раз.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

import aiosqlite

from db.connection import get_db, get_write_lock

logger = logging.getLogger(__name__)

# Результат mark_paid() — различаем четыре случая, чтобы webhook-сервер мог
# ответить провайдеру корректным error-кодом. До фикса возвращали просто None
# для всех нон-paid случаев, и сервер отвечал Success даже на оплату cancelled
# записи → реальный риск: клиент оплачивает старой ссылкой отменённую запись,
# провайдер списывает деньги, бот молчит. Теперь cancelled → провайдер видит
# error и возвращает деньги.
MarkPaidStatus = Literal["paid", "duplicate", "cancelled", "not_found"]


async def attach_invoice(
    appt_id: int, provider: str, invoice_id: str, pay_url: str
) -> bool:
    """
    Привязать invoice к записи ПЕРЕД редиректом клиента на оплату.

    invoice_id — ключ, по которому mark_paid() найдёт запись из webhook.
      • Click: наш appt_id (Click шлёт его как merchant_trans_id).
      • Payme: наш appt_id (invoice_id в Payme = appointment_id).

    pay_url — готовая ссылка для кнопки «Оплатить». Храним чтобы back-door
    в «мои записи» отдал ту же ссылку без повторного create_invoice.

    Возвращает True если привязка прошла, False если у записи уже есть
    invoice — повторный клик по кнопке «Оплатить» отдаёт тот же URL.
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
                "UPDATE appointments SET payment_provider = ?, "
                "payment_invoice_id = ?, payment_pay_url = ? WHERE id = ?",
                (provider, invoice_id, pay_url, appt_id),
            )
            await db.execute("COMMIT")
            return True
        except Exception:
            try:
                await db.execute("ROLLBACK")
            except Exception:
                pass
            raise


async def mark_paid(
    provider: str, invoice_id: str
) -> tuple[MarkPaidStatus, int | None]:
    """
    Пометить запись оплаченной по (provider, invoice_id).

    Возвращает (status, appt_id):
      • ("paid", id)      — первая успешная пометка; сервер уведомляет клиента/админов.
      • ("duplicate", id) — paid_at уже был (дубль-webhook от провайдера).
                            Сервер отвечает Success, клиенту ничего не шлём.
      • ("cancelled", id) — запись отменена до прихода webhook. Сервер ДОЛЖЕН
                            вернуть провайдеру ошибку, иначе провайдер спишет
                            с клиента деньги без услуги. Рефанд — автоматом у
                            провайдера по его error-коду.
      • ("not_found", None) — invoice не найден (левый webhook или race c
                              attach_invoice). Сервер возвращает Success, чтобы
                              провайдер не ретраил бесконечно.
    """
    lock = await get_write_lock()
    async with lock:
        db = await get_db()
        try:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT id, paid_at, status FROM appointments "
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
                return ("not_found", None)
            appt_id, already_paid, status = row
            if already_paid:
                await db.execute("ROLLBACK")
                logger.info(
                    "mark_paid: дубль webhook appt=%s invoice=%s — игнор",
                    appt_id, invoice_id,
                )
                return ("duplicate", appt_id)
            if status == "cancelled":
                await db.execute("ROLLBACK")
                logger.warning(
                    "mark_paid: запись отменена appt=%s invoice=%s — "
                    "отклоняем webhook, провайдер вернёт деньги клиенту",
                    appt_id, invoice_id,
                )
                return ("cancelled", appt_id)
            await db.execute(
                "UPDATE appointments SET paid_at = datetime('now') WHERE id = ?",
                (appt_id,),
            )
            await db.execute("COMMIT")
            return ("paid", appt_id)
        except Exception:
            try:
                await db.execute("ROLLBACK")
            except Exception:
                pass
            raise


async def mark_paid_manual(appt_id: int) -> bool:
    """
    Ручная пометка оплачено админом. Резервный путь на случай пропущенного
    webhook (DNS, рестарт бота, упавший туннель и т.п.).

    Идемпотентно: если paid_at уже стоит — возвращает False.
    provider="manual" чтобы в аналитике отличать от click/payme.
    """
    lock = await get_write_lock()
    async with lock:
        db = await get_db()
        try:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT id, paid_at FROM appointments WHERE id = ?", (appt_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                await db.execute("ROLLBACK")
                return False
            _, already_paid = row
            if already_paid:
                await db.execute("ROLLBACK")
                return False
            # provider/invoice перезаписываем только если они ещё пустые —
            # не затираем реальный click/payme invoice, если он был (вдруг
            # webhook всё-таки придёт позже).
            await db.execute(
                "UPDATE appointments "
                "SET paid_at = datetime('now'), "
                "    payment_provider = COALESCE(payment_provider, 'manual'), "
                "    payment_invoice_id = COALESCE(payment_invoice_id, ?) "
                "WHERE id = ?",
                (f"manual_{appt_id}", appt_id),
            )
            await db.execute("COMMIT")
            return True
        except Exception:
            try:
                await db.execute("ROLLBACK")
            except Exception:
                pass
            raise


async def get_payment_state(appt_id: int) -> dict[str, Any] | None:
    """Прочитать платёжные поля + сумму + статус. None если записи нет.

    status нужен payme.verify_and_parse, чтобы отказать на CheckPerformTransaction
    для отменённых записей — иначе Payme разрешит оплату в никуда.
    payment_message_id — чтобы удалить pay-сообщение после оплаты (иначе
    клиент тапнет старую кнопку второй раз и Click спишет повторно).
    """
    db = await get_db()
    cursor = await db.execute(
        "SELECT paid_at, payment_provider, payment_invoice_id, payment_pay_url, "
        "       service_price, user_id, name, service_name, date, time, status, "
        "       payment_message_id "
        "FROM appointments WHERE id = ?",
        (appt_id,),
    )
    cursor.row_factory = aiosqlite.Row
    row = await cursor.fetchone()
    return dict(row) if row else None


async def save_pay_message_id(appt_id: int, message_id: int) -> None:
    """
    Запомнить message_id сообщения «💳 ссылка на оплату» чтобы удалить его
    после успешной оплаты. Не транзакция — одиночный UPDATE, ошибка не должна
    валить основной booking-flow (лучше дубль-оплата, чем упавший confirm).
    """
    db = await get_db()
    try:
        await db.execute(
            "UPDATE appointments SET payment_message_id = ? WHERE id = ?",
            (message_id, appt_id),
        )
        await db.commit()
    except Exception:
        logger.warning(
            "не сохранил payment_message_id appt=%s msg=%s", appt_id, message_id,
            exc_info=True,
        )
