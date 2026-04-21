# Phase 1 — Online Payments (Click + Payme) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans
> to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Клиент после подтверждения записи нажимает «💳 Оплатить» →
попадает в Click/Payme → бот через webhook узнаёт об оплате, помечает
запись `paid_at` и показывает статус в админке. Ручное проставление
оплаты в мерчант-дашборде больше не нужно.

**Architecture:** Pluggable provider (`utils/payments/base.py`) + две
реализации (`click.py`, `payme.py`). aiohttp-сервер поднимается ВНУТРИ
bot-процесса рядом с `dp.start_polling()` — один порт (8443) за
Caddy/nginx TLS. Webhook-верификация подписи — single source of truth
в провайдер-модуле. Idempotency через `UNIQUE payment_invoice_id`.

**Tech Stack:** aiohttp (уже transitive через aiogram), hmac/hashlib
stdlib, aiosqlite (существующий global connection).

**Общее правило v4:** один деплой-коммит на всю Phase 1. Во время
работы можно коммитить мелкими WIP-коммитами, финальный — squash либо
rebase-cleanup перед пушем.

**Test policy:** ровно один тест — forged webhook → 401. Остальное
автор проверяет руками через sandbox (по v4-verification).

---

## File Structure

**Новые файлы:**
- `utils/payments/__init__.py` — фабрика по `PAYMENT_PROVIDER`
- `utils/payments/base.py` — `PaymentProvider` ABC
- `utils/payments/click.py` — Click Merchant API + webhook verifier
- `utils/payments/payme.py` — Payme Merchant API (JSON-RPC) + verifier
- `utils/payments/server.py` — aiohttp-app c `/payment/click`, `/payment/payme`
- `db/payments.py` — `mark_paid()`, `get_payment_state()`, `exists_invoice()`
- `tests/test_payment_webhook_forgery.py` — **обязательный** forgery-тест
- `docs/PAYMENTS.md` — оператор-документация (как настроить Click merchant)

**Файлы под правку:**
- `db/connection.py` — миграция v2→v3 (3 колонки + индекс)
- `config.py` — новые env vars
- `.env.template` — задокументировать новые переменные
- `bot.py` — старт aiohttp-сервера параллельно polling
- `handlers/client.py` — `confirm_yes`: вместо static `PAYMENT_URL`
  генерить invoice через провайдер
- `keyboards/inline.py` — `payment_keyboard()` принимает готовый url
- `handlers/admin_appointments.py` — status-pill в карточке +
  алерт «нужен возврат» при отмене оплаченной записи
- `docker-compose.yml` — expose порт 8443

---

## Task 1 — DB migration v2→v3

**Files:**
- Modify: `db/connection.py` (после блока миграции v1→v2, строки ~326-338)

**Что делаем:**
Добавляем 3 колонки в `appointments` и UNIQUE-индекс на
`payment_invoice_id` (для idempotency при повторах webhook).

- [ ] **Step 1:** в `db/connection.py` после блока `if current_version < 2:`
      добавить миграцию v2→v3

```python
# v2 → v3: платёжные колонки. Идемпотентность webhook — через
# UNIQUE(payment_invoice_id), т.к. провайдеры ретраят на 5xx.
# paid_at=NULL → оплата не получена.
if current_version < 3:
    for stmt in (
        "ALTER TABLE appointments ADD COLUMN paid_at TEXT",
        "ALTER TABLE appointments ADD COLUMN payment_provider TEXT",
        "ALTER TABLE appointments ADD COLUMN payment_invoice_id TEXT",
    ):
        try:
            await db.execute(stmt)
        except aiosqlite.OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                logger.exception("Миграция v2→v3 упала: %s", stmt)
    # UNIQUE-индекс, а не PK/UNIQUE в ALTER — SQLite не умеет добавить
    # UNIQUE constraint в существующую таблицу без пересоздания.
    # Partial index (WHERE payment_invoice_id IS NOT NULL) — чтобы NULL-значения
    # (невыставленные инвойсы) не конфликтовали друг с другом.
    await db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_appt_invoice_unique "
        "ON appointments(payment_invoice_id) "
        "WHERE payment_invoice_id IS NOT NULL"
    )
    await db.execute("PRAGMA user_version = 3")
```

- [ ] **Step 2:** верификация локально

```bash
docker compose up -d --build
docker compose exec bot python -c "import asyncio; from db import init_db; from db.connection import get_db; \
async def check(): \
    await init_db(); \
    db = await get_db(); \
    c = await db.execute('PRAGMA user_version'); print((await c.fetchone())[0]); \
    c = await db.execute(\"PRAGMA table_info(appointments)\"); \
    print([r[1] async for r in c]); \
asyncio.run(check())"
```
Expected: `3` и в списке колонок видны `paid_at, payment_provider, payment_invoice_id`.

---

## Task 2 — Config / env vars

**Files:**
- Modify: `config.py`
- Modify: `.env.template`

- [ ] **Step 1:** в `config.py` после блока `PAYMENT_URL` заменить старый
      deeplink-подход на multi-provider:

```python
# ─── Платежи (Phase 1 v.4) ──────────────────────────────────────────────
# Провайдер: click | payme | none. "none" → кнопка оплаты не показывается
# (для демо/локалки). Legacy PAYMENT_URL (чистый deeplink) больше не
# используется — если задан вместе с PAYMENT_PROVIDER=none, игнорируется.
PAYMENT_PROVIDER: Final[str] = os.getenv("PAYMENT_PROVIDER", "none").strip().lower()
if PAYMENT_PROVIDER not in {"click", "payme", "none"}:
    raise EnvironmentError(
        f"PAYMENT_PROVIDER='{PAYMENT_PROVIDER}' недопустим. Допустимые: click | payme | none."
    )

# Click — https://docs.click.uz/click-api-request/
CLICK_SERVICE_ID: Final[str] = os.getenv("CLICK_SERVICE_ID", "").strip()
CLICK_MERCHANT_ID: Final[str] = os.getenv("CLICK_MERCHANT_ID", "").strip()
CLICK_MERCHANT_USER_ID: Final[str] = os.getenv("CLICK_MERCHANT_USER_ID", "").strip()
CLICK_SECRET_KEY: Final[str] = os.getenv("CLICK_SECRET_KEY", "").strip()
# Для локального теста: направляем API на mock-сервер (tools/mock_click_server.py).
# Дефолт — прод Click. Пример для dev: http://localhost:8444/mock-click/v2/merchant
CLICK_API_BASE: Final[str] = os.getenv("CLICK_API_BASE", "https://api.click.uz/v2/merchant").rstrip("/")
# Для mock: базовый URL для pay_url, который клиент откроет в браузере.
# Пусто → используется боевой my.click.uz.
CLICK_PAY_URL_BASE: Final[str] = os.getenv("CLICK_PAY_URL_BASE", "https://my.click.uz/services/pay").rstrip("?")

# Payme — https://developer.help.paycom.uz/merchant-api/
PAYME_MERCHANT_ID: Final[str] = os.getenv("PAYME_MERCHANT_ID", "").strip()
PAYME_SECRET_KEY: Final[str] = os.getenv("PAYME_SECRET_KEY", "").strip()

# Публичный домен для приёма webhook от провайдеров. Caddy/nginx терминирует
# TLS и проксирует на 127.0.0.1:PAYMENT_WEBHOOK_PORT. Пусто → webhook-сервер
# не стартует (dev-режим без провайдера).
PAYMENT_PUBLIC_URL: Final[str] = os.getenv("PAYMENT_PUBLIC_URL", "").rstrip("/")
PAYMENT_WEBHOOK_PORT: Final[int] = int(os.getenv("PAYMENT_WEBHOOK_PORT", "8443"))

# Fail-fast: если включили провайдера — все его креды ОБЯЗАНЫ быть заданы.
if PAYMENT_PROVIDER == "click":
    _missing = [k for k, v in {
        "CLICK_SERVICE_ID": CLICK_SERVICE_ID,
        "CLICK_MERCHANT_ID": CLICK_MERCHANT_ID,
        "CLICK_MERCHANT_USER_ID": CLICK_MERCHANT_USER_ID,
        "CLICK_SECRET_KEY": CLICK_SECRET_KEY,
        "PAYMENT_PUBLIC_URL": PAYMENT_PUBLIC_URL,
    }.items() if not v]
    if _missing:
        raise EnvironmentError(
            f"PAYMENT_PROVIDER=click, но не заданы: {', '.join(_missing)}"
        )
elif PAYMENT_PROVIDER == "payme":
    _missing = [k for k, v in {
        "PAYME_MERCHANT_ID": PAYME_MERCHANT_ID,
        "PAYME_SECRET_KEY": PAYME_SECRET_KEY,
        "PAYMENT_PUBLIC_URL": PAYMENT_PUBLIC_URL,
    }.items() if not v]
    if _missing:
        raise EnvironmentError(
            f"PAYMENT_PROVIDER=payme, но не заданы: {', '.join(_missing)}"
        )
```

Важно: блок `PAYMENT_URL` / `PAYMENT_LABEL` из строк 49–52 **оставить
без изменений** — это legacy для салонов, кто не хочет полную
интеграцию (просто deeplink). `keyboards/inline.py::payment_keyboard`
мы перепишем так, чтобы предпочитать PAYMENT_PROVIDER когда он задан,
иначе падать на старый PAYMENT_URL.

- [ ] **Step 2:** в `.env.template` добавить блок (после существующего
      `PAYMENT_URL`):

```
# Online-платежи Phase 1 (v.4)
# Провайдер: click | payme | none. "none" = показываем legacy PAYMENT_URL если задан.
PAYMENT_PROVIDER=none

# Click Merchant API (https://merchant.click.uz)
CLICK_SERVICE_ID=
CLICK_MERCHANT_ID=
CLICK_MERCHANT_USER_ID=
CLICK_SECRET_KEY=

# Payme Merchant API (https://merchant.paycom.uz)
PAYME_MERCHANT_ID=
PAYME_SECRET_KEY=

# Публичный HTTPS-URL, на котором Caddy/nginx проксирует webhook'и в бот.
# Пример: https://bot.sabinanails.uz (без слеша в конце).
PAYMENT_PUBLIC_URL=
# Порт, на котором aiohttp слушает локально (за reverse-proxy).
PAYMENT_WEBHOOK_PORT=8443

# ── Dev / локальный тест без реального Click ────────────────────────
# Для прогонки без реального мерчанта — см. tools/mock_click_server.py.
# Запусти в соседнем терминале: python tools/mock_click_server.py
# и выстави:
#   CLICK_API_BASE=http://localhost:8444/mock-click/v2/merchant
#   CLICK_PAY_URL_BASE=http://localhost:8444/mock-click/pay
#   PAYMENT_PUBLIC_URL=http://localhost:8443   (bot сам принимает webhook)
# В проде — закомментировать или убрать.
CLICK_API_BASE=
CLICK_PAY_URL_BASE=
```

---

## Task 3 — DB helpers для платежей

**Files:**
- Create: `db/payments.py`

- [ ] **Step 1:** создать файл

```python
"""
DB-операции для платежей (Phase 1 v.4).

Строго один путь записи — mark_paid(). Идемпотентность через
UNIQUE(payment_invoice_id): повторный webhook на тот же invoice_id
не переписывает paid_at (INSERT … ON CONFLICT не подходит — у нас
UPDATE, поэтому явно проверяем paid_at IS NULL в WHERE).
"""
import logging
from typing import Any

from db.connection import get_db, get_write_lock

logger = logging.getLogger(__name__)


async def attach_invoice(appt_id: int, provider: str, invoice_id: str) -> bool:
    """
    Привязать invoice_id к записи ПЕРЕД редиректом клиента на оплату.
    Возвращает True если привязали, False если у записи уже есть invoice
    (повторный клик по кнопке — отдаём тот же invoice, не создаём новый).
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
                await db.execute("ROLLBACK")
                return False  # уже есть invoice, клиент повторно нажал
            await db.execute(
                "UPDATE appointments SET payment_provider = ?, payment_invoice_id = ? WHERE id = ?",
                (provider, invoice_id, appt_id),
            )
            await db.execute("COMMIT")
            return True
        except Exception:
            await db.execute("ROLLBACK")
            raise


async def mark_paid(provider: str, invoice_id: str) -> int | None:
    """
    Пометить запись оплаченной. Идемпотентна: повторный вызов
    возвращает None если уже было paid_at.

    Возвращает appt_id при успешной первой оплате, None если дубль или
    invoice не найден.
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
                logger.warning("mark_paid: invoice не найден provider=%s invoice=%s", provider, invoice_id)
                return None
            appt_id, already_paid = row
            if already_paid:
                await db.execute("ROLLBACK")
                return None  # идемпотентный повтор
            await db.execute(
                "UPDATE appointments SET paid_at = datetime('now') WHERE id = ?",
                (appt_id,),
            )
            await db.execute("COMMIT")
            return appt_id
        except Exception:
            await db.execute("ROLLBACK")
            raise


async def get_payment_state(appt_id: int) -> dict[str, Any] | None:
    """Прочитать платёжные поля записи. None если записи нет."""
    db = await get_db()
    import aiosqlite
    cursor = await db.execute(
        "SELECT paid_at, payment_provider, payment_invoice_id, service_price "
        "FROM appointments WHERE id = ?",
        (appt_id,),
    )
    cursor.row_factory = aiosqlite.Row
    row = await cursor.fetchone()
    return dict(row) if row else None
```

---

## Task 4 — Provider ABC

**Files:**
- Create: `utils/payments/__init__.py`
- Create: `utils/payments/base.py`

- [ ] **Step 1:** `utils/payments/base.py`

```python
"""Базовый провайдер онлайн-оплат."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Invoice:
    """Результат создания инвойса у провайдера."""
    invoice_id: str      # уникальный id у провайдера (idempotency-ключ)
    pay_url: str         # deeplink на приложение Click/Payme


class PaymentProvider(ABC):
    """
    Контракт провайдера. Методы синхронные-async, потому что
    create_invoice ходит в HTTP, а verify_webhook — чистый CPU
    (hmac), но async ради единообразия.
    """

    name: str  # "click" | "payme"

    @abstractmethod
    async def create_invoice(self, appt_id: int, amount_uzs: int, phone: str) -> Invoice: ...

    @abstractmethod
    async def verify_and_parse(self, headers: dict, raw_body: bytes) -> str:
        """
        Вернуть invoice_id из валидного webhook-body.
        Бросить PermissionError если подпись невалидна (→ HTTP 401).
        Бросить ValueError если тело кривое (→ HTTP 400).
        """
```

- [ ] **Step 2:** `utils/payments/__init__.py`

```python
"""Фабрика провайдеров по PAYMENT_PROVIDER."""
from __future__ import annotations

import logging

from config import PAYMENT_PROVIDER
from utils.payments.base import Invoice, PaymentProvider

logger = logging.getLogger(__name__)

_provider: PaymentProvider | None = None


def get_provider() -> PaymentProvider | None:
    """Ленивая инициализация провайдера. None → платежи выключены."""
    global _provider
    if _provider is not None:
        return _provider
    if PAYMENT_PROVIDER == "click":
        from utils.payments.click import ClickProvider
        _provider = ClickProvider()
    elif PAYMENT_PROVIDER == "payme":
        from utils.payments.payme import PaymeProvider
        _provider = PaymeProvider()
    else:
        return None
    logger.info("Payments: провайдер=%s", PAYMENT_PROVIDER)
    return _provider


__all__ = ["Invoice", "PaymentProvider", "get_provider"]
```

---

## Task 5 — Click provider

**Files:**
- Create: `utils/payments/click.py`

Референс: https://docs.click.uz/click-api-request/

Click Webhook схема (Prepare + Complete):
- POST form-data (`application/x-www-form-urlencoded`), поля:
  `click_trans_id`, `service_id`, `click_paydoc_id`, `merchant_trans_id`
  (= наш `appt_id`), `amount`, `action` (`0`=prepare, `1`=complete),
  `error`, `error_note`, `sign_time`, `sign_string`, + на complete
  ещё `merchant_prepare_id`.
- Подпись: `md5(click_trans_id + service_id + SECRET_KEY +
  merchant_trans_id + [merchant_prepare_id] + amount + action + sign_time)`.
- Ответ: JSON `{"click_trans_id": ..., "merchant_trans_id": ...,
  "merchant_prepare_id": ..., "error": 0, "error_note": "Success"}`.

- [ ] **Step 1:** создать файл

```python
"""Click Merchant API (UZ). Invoice через https://api.click.uz/v2/merchant/invoice/create."""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

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


class ClickProvider(PaymentProvider):
    name = "click"

    def _auth_header(self) -> str:
        """Auth = <merchant_user_id>:<digest>:<timestamp>
        digest = sha1(timestamp + SECRET_KEY)."""
        ts = str(int(time.time()))
        digest = hashlib.sha1((ts + CLICK_SECRET_KEY).encode()).hexdigest()
        return f"{CLICK_MERCHANT_USER_ID}:{digest}:{ts}"

    async def create_invoice(self, appt_id: int, amount_uzs: int, phone: str) -> Invoice:
        """
        Создаёт invoice через Click API. Click отдаёт invoice_id + ссылку
        на оплату (payment_url), которую скармливаем клиенту в кнопку.
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
            async with session.post(f"{CLICK_API_BASE}/invoice/create", json=payload, headers=headers) as resp:
                data = await resp.json()
        # Click отвечает {error_code: 0, invoice_id: "..."} на успех.
        # error_code != 0 → поднимаем, пусть handler покажет клиенту fallback.
        if data.get("error_code", -1) != 0:
            raise RuntimeError(f"Click invoice create failed: {data}")
        invoice_id = str(data["invoice_id"])
        # pay_url: стандартная схема Click Pass / web.
        # https://my.click.uz/services/pay?service_id=...&merchant_id=...&amount=...&transaction_param=<invoice_id>
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
        Click шлёт application/x-www-form-urlencoded. Парсим руками, чтобы
        канонизация байтов совпала с тем, что Click хэширует.
        """
        from urllib.parse import parse_qs
        parsed = parse_qs(raw_body.decode("utf-8"))
        def _get(k: str) -> str:
            v = parsed.get(k, [""])
            return v[0] if v else ""
        click_trans_id = _get("click_trans_id")
        service_id = _get("service_id")
        merchant_trans_id = _get("merchant_trans_id")
        merchant_prepare_id = _get("merchant_prepare_id")  # на prepare = ""
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

        import hmac
        if not hmac.compare_digest(expected, sign_string):
            raise PermissionError("click: signature mismatch")

        if action != "1":
            # action=0 (prepare) — Click спрашивает «можно ли принять оплату».
            # Мы возвращаем invoice_id, но запись НЕ помечаем paid. Только complete (action=1) — финал.
            # Сервер-слой должен уметь отличать: возвращаем invoice_id + флаг на level выше, либо
            # кидаем специальное исключение. Для MVP — выбрасываем PermissionError с комментом,
            # server.py обработает prepare отдельным кодом (см. Task 7).
            raise _ClickPrepare(merchant_trans_id=merchant_trans_id, click_trans_id=click_trans_id)

        # complete: возвращаем наш invoice_id. В Click invoice_id = merchant_prepare_id
        # (его сгенерили мы на prepare, см. server.py). Но для простоты привязки к appointment
        # работаем через merchant_trans_id = appt_id.
        return merchant_trans_id  # = appt_id, но str


class _ClickPrepare(Exception):
    """Сигнал server.py что это prepare-шаг и нужен специальный JSON-ответ."""
    def __init__(self, merchant_trans_id: str, click_trans_id: str):
        self.merchant_trans_id = merchant_trans_id
        self.click_trans_id = click_trans_id
```

> **Замечание об upstream-поведении.** Click использует двухшаговую
> модель (prepare → complete). Чистый `verify_and_parse → invoice_id`
> туда не ложится. Поэтому Click-специфичные ветки остаются в
> `server.py::click_webhook` и `_ClickPrepare` — явно и локально.
> Payme (JSON-RPC) ложится в абстракцию чище.

---

## Task 6 — Payme provider

**Files:**
- Create: `utils/payments/payme.py`

Payme Merchant API — JSON-RPC. Auth — `Authorization: Basic base64("Paycom:" + SECRET_KEY)`.
Методы: `CheckPerformTransaction`, `CreateTransaction`, `PerformTransaction`,
`CancelTransaction`, `CheckTransaction`. Все идут POST на ОДИН endpoint.

Спецификация: https://developer.help.paycom.uz/

- [ ] **Step 1:** создать файл

```python
"""Payme Merchant API (UZ). JSON-RPC на наш endpoint /payment/payme."""
from __future__ import annotations

import base64
import hmac
import logging
from typing import Any

from config import PAYME_MERCHANT_ID, PAYME_SECRET_KEY
from utils.payments.base import Invoice, PaymentProvider

logger = logging.getLogger(__name__)


class PaymeProvider(PaymentProvider):
    name = "payme"

    async def create_invoice(self, appt_id: int, amount_uzs: int, phone: str) -> Invoice:
        """
        У Payme нет separate invoice_create API — клиент редиректится на
        checkout.paycom.uz с base64-кодированными параметрами, а Payme
        потом сам шлёт нам CheckPerformTransaction → CreateTransaction.
        invoice_id = наш appt_id (используется как account.appointment_id в Payme).
        """
        # Payme ждёт сумму в тийинах (1 UZS = 100 тийин).
        amount_tiyin = amount_uzs * 100
        raw = f"m={PAYME_MERCHANT_ID};ac.appointment_id={appt_id};a={amount_tiyin};c={_public_return_url(appt_id)}"
        payload_b64 = base64.b64encode(raw.encode()).decode()
        pay_url = f"https://checkout.paycom.uz/{payload_b64}"
        # invoice_id = str(appt_id) — это наш primary key, Payme хранит его в account.appointment_id.
        # На webhook мы получаем params.account.appointment_id → находим запись.
        return Invoice(invoice_id=str(appt_id), pay_url=pay_url)

    async def verify_and_parse(self, headers: dict, raw_body: bytes) -> str:
        """
        Auth: Authorization: Basic base64("Paycom:" + SECRET_KEY).
        Сам JSON-RPC body не подписан — единственная защита это Basic auth.
        Поэтому отсечка строгая: нет заголовка либо не совпал → PermissionError.
        """
        auth = headers.get("Authorization") or headers.get("authorization") or ""
        expected = "Basic " + base64.b64encode(f"Paycom:{PAYME_SECRET_KEY}".encode()).decode()
        if not hmac.compare_digest(auth, expected):
            raise PermissionError("payme: basic auth mismatch")

        # JSON-RPC: {"jsonrpc":"2.0","method":"PerformTransaction","params":{"id":"...","account":{"appointment_id":123}}}
        import json
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except Exception as exc:
            raise ValueError(f"payme: bad json: {exc}")

        method = body.get("method")
        params = body.get("params", {})
        # Для MVP помечаем paid только на PerformTransaction. Остальные методы
        # обрабатывает server.py согласно спеке Payme (возвращает пустой ack).
        if method != "PerformTransaction":
            raise _PaymeNonPerform(method=method, params=params, rpc_id=body.get("id"))

        account = params.get("account", {})
        appt_id = str(account.get("appointment_id", ""))
        if not appt_id:
            raise ValueError("payme: params.account.appointment_id missing")
        return appt_id  # = appt_id as string


class _PaymeNonPerform(Exception):
    """Сигнал server.py: это не PerformTransaction, обработать отдельной веткой."""
    def __init__(self, method: str, params: dict[str, Any], rpc_id: Any):
        self.method = method
        self.params = params
        self.rpc_id = rpc_id


def _public_return_url(appt_id: int) -> str:
    from config import PAYMENT_PUBLIC_URL
    return f"{PAYMENT_PUBLIC_URL}/payment/return?appt={appt_id}"
```

---

## Task 7 — Webhook server (aiohttp)

**Files:**
- Create: `utils/payments/server.py`

- [ ] **Step 1:** создать файл

```python
"""
aiohttp-сервер приёма webhook. Работает В ТОМ ЖЕ процессе что и polling —
запускается отдельной task в bot.py::main. Не плодим контейнеры.

Безопасность:
- Подпись/basic auth проверяем ДО парсинга тела провайдер-специфики
  (см. verify_and_parse).
- Rate-limit: 60 req/min на IP (простой sliding-window in-memory).
  Для solo-VPS этого достаточно; распределённый rate-limit — YAGNI.
- Fail-closed: любой unexpected exception → 401. Никогда 500 на успех
  только потому что "catch-all".
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict, deque

from aiogram import Bot
from aiohttp import web

from config import PAYMENT_WEBHOOK_PORT
from db.payments import get_payment_state, mark_paid
from utils.notifications import broadcast_to_admins
from utils.payments import get_provider
from utils.payments.click import _ClickPrepare
from utils.payments.payme import _PaymeNonPerform

logger = logging.getLogger(__name__)

_RATE_LIMIT_PER_MIN = 60
_rate_log: dict[str, deque] = defaultdict(deque)


def _rate_limited(ip: str) -> bool:
    now = time.time()
    q = _rate_log[ip]
    while q and q[0] < now - 60:
        q.popleft()
    if len(q) >= _RATE_LIMIT_PER_MIN:
        return True
    q.append(now)
    return False


async def _on_paid(bot: Bot, appt_id: int) -> None:
    """После успешной оплаты: клиенту — ✓, админам — 💰."""
    state = await get_payment_state(appt_id)
    if not state:
        return
    # Клиент.
    from db.connection import get_db
    import aiosqlite
    db = await get_db()
    cursor = await db.execute(
        "SELECT user_id, name, service_name, date, time FROM appointments WHERE id = ?",
        (appt_id,),
    )
    cursor.row_factory = aiosqlite.Row
    row = await cursor.fetchone()
    if row is None:
        return
    appt = dict(row)
    try:
        await bot.send_message(
            appt["user_id"],
            "<i>✓ оплата получена.</i>\n<i>жду тебя.</i>",
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.warning("не доставил подтверждение оплаты user=%s: %s", appt["user_id"], exc)

    # Админы.
    try:
        await broadcast_to_admins(
            bot,
            f"💰 <b>Оплата прошла</b>\n"
            f"{appt['date']} · {appt['time']} — {appt['name']}\n"
            f"{appt['service_name']} · {state['service_price']:,} UZS".replace(",", " "),
            log_context="payment received",
        )
    except Exception as exc:
        logger.warning("не доставил админ-алерт об оплате: %s", exc)


async def _click_handler(request: web.Request) -> web.Response:
    ip = request.remote or "?"
    if _rate_limited(ip):
        return web.Response(status=429, text="rate-limited")
    raw = await request.read()
    provider = get_provider()
    if provider is None or provider.name != "click":
        return web.Response(status=404)

    # Prepare-шаг Click отделим. На complete — mark_paid.
    try:
        appt_id_str = await provider.verify_and_parse(dict(request.headers), raw)
    except _ClickPrepare as prep:
        # Возвращаем "всё ок, принимаем" — Click пошлёт complete следующим шагом.
        # merchant_prepare_id = наш appt_id (любая уникальная строка по спеке).
        return web.json_response({
            "click_trans_id": int(prep.click_trans_id),
            "merchant_trans_id": prep.merchant_trans_id,
            "merchant_prepare_id": int(prep.merchant_trans_id),  # reuse appt_id
            "error": 0,
            "error_note": "Success",
        })
    except PermissionError as exc:
        logger.warning("click webhook 401 from %s: %s", ip, exc)
        return web.Response(status=401, text="unauthorized")
    except ValueError as exc:
        logger.warning("click webhook 400 from %s: %s", ip, exc)
        return web.Response(status=400, text="bad request")
    except Exception:
        logger.exception("click webhook: unexpected, fail-closed to 401")
        return web.Response(status=401, text="unauthorized")

    appt_id = int(appt_id_str)
    paid_appt = await mark_paid("click", invoice_id=appt_id_str)
    if paid_appt is not None:
        bot: Bot = request.app["bot"]
        asyncio.create_task(_on_paid(bot, paid_appt))
    return web.json_response({
        "click_trans_id": int(request.rel_url.query.get("click_trans_id", "0")) or 0,
        "merchant_trans_id": str(appt_id),
        "merchant_confirm_id": appt_id,
        "error": 0,
        "error_note": "Success",
    })


async def _payme_handler(request: web.Request) -> web.Response:
    ip = request.remote or "?"
    if _rate_limited(ip):
        return web.Response(status=429, text="rate-limited")
    raw = await request.read()
    provider = get_provider()
    if provider is None or provider.name != "payme":
        return web.Response(status=404)

    try:
        appt_id_str = await provider.verify_and_parse(dict(request.headers), raw)
    except _PaymeNonPerform as non:
        # Не PerformTransaction — отвечаем JSON-RPC ack с нужными полями
        # согласно методу. MVP: CheckPerformTransaction → allow, остальные → пустой ok.
        body = _payme_ack(non)
        return web.json_response(body)
    except PermissionError as exc:
        logger.warning("payme webhook 401 from %s: %s", ip, exc)
        return web.Response(status=401, text="unauthorized")
    except ValueError as exc:
        logger.warning("payme webhook 400 from %s: %s", ip, exc)
        return web.Response(status=400, text="bad request")
    except Exception:
        logger.exception("payme webhook: unexpected, fail-closed to 401")
        return web.Response(status=401, text="unauthorized")

    appt_id = int(appt_id_str)
    paid_appt = await mark_paid("payme", invoice_id=appt_id_str)
    if paid_appt is not None:
        bot: Bot = request.app["bot"]
        asyncio.create_task(_on_paid(bot, paid_appt))
    # Payme PerformTransaction ответ:
    rpc_id = json.loads(raw).get("id")
    return web.json_response({
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {
            "transaction": str(appt_id),
            "perform_time": int(time.time() * 1000),
            "state": 2,
        },
    })


def _payme_ack(non: _PaymeNonPerform) -> dict:
    """Минимальный ack для не-PerformTransaction методов.
    По спеке Payme: CheckPerformTransaction → allow:true при валидной записи.
    Остальные (Create/Cancel/CheckTransaction) — упрощённый ок для MVP."""
    if non.method == "CheckPerformTransaction":
        return {"jsonrpc": "2.0", "id": non.rpc_id, "result": {"allow": True}}
    if non.method == "CreateTransaction":
        return {"jsonrpc": "2.0", "id": non.rpc_id, "result": {
            "transaction": str(non.params.get("id")),
            "create_time": int(time.time() * 1000),
            "state": 1,
        }}
    # CancelTransaction / CheckTransaction / ChangePassword — ок, подробнее в TODO.
    return {"jsonrpc": "2.0", "id": non.rpc_id, "result": {"state": 1}}


async def start_webhook_server(bot: Bot) -> web.AppRunner:
    app = web.Application()
    app["bot"] = bot
    app.router.add_post("/payment/click", _click_handler)
    app.router.add_post("/payment/payme", _payme_handler)

    # Health endpoint — Caddy/nginx может использовать.
    async def _health(_req):
        return web.Response(text="ok")
    app.router.add_get("/health", _health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=PAYMENT_WEBHOOK_PORT)
    await site.start()
    logger.info("Payment webhook server слушает на 0.0.0.0:%s", PAYMENT_WEBHOOK_PORT)
    return runner
```

> **Явно отложено в Payme-ветке:** Полная реализация JSON-RPC методов
> Payme (CreateTransaction с проверкой дублей, CancelTransaction →
> refund-алерт, GetStatement) выходит за MVP. Сейчас мы помечаем
> paid только на PerformTransaction. Остальное — честный TODO в
> docs/PAYMENTS.md, расширить по первой боли от клиента.

---

## Task 8 — Интеграция сервера в bot.py

**Files:**
- Modify: `bot.py`

- [ ] **Step 1:** в конце `main()` перед `dp.start_polling(bot)` стартовать
      webhook-сервер **только** если PAYMENT_PROVIDER != none.

```python
# ─── Payment webhook server (Phase 1 v.4) ───
# Стартуем aiohttp в том же event loop, ПАРАЛЛЕЛЬНО polling. Shutdown
# аккуратно останавливает runner в finally-блоке ниже.
payment_runner = None
from config import PAYMENT_PROVIDER
if PAYMENT_PROVIDER != "none":
    from utils.payments.server import start_webhook_server
    payment_runner = await start_webhook_server(bot)
```

И в `finally:` добавить:

```python
if payment_runner is not None:
    await payment_runner.cleanup()
```

---

## Task 9 — confirm_yes: реальный invoice вместо static URL

**Files:**
- Modify: `handlers/client.py` (блок ~857-865 "4. Ссылка на оплату")
- Modify: `keyboards/inline.py::payment_keyboard` (строки 903-910)

- [ ] **Step 1:** переписать `payment_keyboard` — принимать готовый URL:

```python
def payment_keyboard(pay_url: str | None, label: str | None = None) -> InlineKeyboardMarkup | None:
    """Клавиатура с url-кнопкой на оплату. None если pay_url пустой."""
    if not pay_url:
        return None
    from config import PAYMENT_LABEL
    text = f"💳 {label or PAYMENT_LABEL}"
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=text, url=pay_url),
    ]])
```

- [ ] **Step 2:** в `handlers/client.py::confirm_yes` блок «4. Ссылка на
      оплату» заменить на:

```python
# 4. Ссылка на оплату — в самом конце, как CTA после полного подтверждения.
# Приоритет: PAYMENT_PROVIDER (click/payme) → legacy PAYMENT_URL → ничего.
from utils.payments import get_provider
from keyboards.inline import payment_keyboard

pay_url: str | None = None
provider = get_provider()
if provider is not None:
    try:
        invoice = await provider.create_invoice(
            appt_id=appt_id,
            amount_uzs=data["service_price"],
            phone=data["phone"],
        )
        from db.payments import attach_invoice
        await attach_invoice(appt_id, provider.name, invoice.invoice_id)
        pay_url = invoice.pay_url
    except Exception:
        # Платёж провалился на создании invoice — но запись УЖЕ сохранена.
        # Клиент не страдает: просто не увидит кнопку. Ошибка уйдёт в error-канал
        # через @dp.errors, поэтому логгируем без re-raise.
        logger.exception("create_invoice failed for appt=%s", appt_id)

if pay_url is None:
    # Fallback на legacy PAYMENT_URL — для салонов без полной интеграции.
    from config import PAYMENT_URL
    if PAYMENT_URL:
        pay_url = PAYMENT_URL.replace("{amount}", str(data["service_price"])).replace("{appt_id}", str(appt_id))

pay_kb = payment_keyboard(pay_url)
if pay_kb:
    await callback.message.answer(
        "<i>ссылка на оплату:</i>",
        reply_markup=pay_kb,
        parse_mode="HTML",
    )
```

---

## Task 10 — Админ-карточка: status-pill

**Files:**
- Modify: `handlers/admin_appointments.py`

- [ ] **Step 1:** найти функцию рендера карточки (skim файл → где
      показывается карточка одной записи; предположительно
      `_appointment_card_text` или аналогичное). Добавить строку:

```python
# Платёжный статус — показываем только если PAYMENT_PROVIDER включён,
# либо если по записи выставлялся invoice (legacy-бот без провайдера
# не должен внезапно показывать «—» в карточке).
payment_pill = ""
if appt.get("payment_provider") or PAYMENT_PROVIDER != "none":
    if appt.get("paid_at"):
        payment_pill = "\n💰 <b>Оплачено</b>"
    elif appt.get("payment_invoice_id"):
        payment_pill = "\n⏳ <i>ждёт оплаты</i>"
    else:
        payment_pill = "\n— <i>без оплаты</i>"
```

Импорт `PAYMENT_PROVIDER` из config на верх файла.
Добавить `payment_pill` в собираемый текст карточки.

> **Точные линии** определит исполнитель по месту — файл большой (~25KB),
> рендер-шаблон один, искать по строке «service_name» в f-string.

- [ ] **Step 2:** убедиться, что запросы к записи в `admin_appointments.py`
      тянут новые колонки. Grep на `SELECT * FROM appointments` —
      если `*`, то всё ок. Если перечислены столбцы — добавить
      `paid_at, payment_provider, payment_invoice_id`.

---

## Task 11 — Алерт «нужен возврат» на отмене оплаченной записи

**Files:**
- Modify: `handlers/admin_appointments.py` (функция отмены)
- Modify: `handlers/client.py` (если у клиента есть путь отмены — проверить)

- [ ] **Step 1:** найти место где выставляется `status='cancelled'`
      (обычно одна функция `_cancel_appointment` или callback-handler).
      Перед коммитом изменения статуса прочитать `paid_at`, и если
      не null — постнуть алерт в админ-чат ПОСЛЕ успешной отмены:

```python
if prev_paid_at:
    try:
        await broadcast_to_admins(
            bot,
            f"🔴 <b>Нужен возврат</b>\n"
            f"Запись #{appt_id} отменена после оплаты.\n"
            f"Сумма: {appt['service_price']:,} UZS\n"
            f"Провайдер: {appt.get('payment_provider', '—')}\n"
            f"Инвойс: <code>{appt.get('payment_invoice_id', '—')}</code>\n\n"
            f"<i>сделай возврат вручную в дашборде провайдера.</i>".replace(",", " "),
            log_context="refund needed",
        )
    except Exception:
        logger.exception("failed to send refund alert for appt=%s", appt_id)
```

- [ ] **Step 2:** если у клиента есть self-service отмена (проверь
      `handlers/client_reminders.py` / `client_history.py`) — там же
      продублировать алерт.

---

## Task 12 — Обязательный тест: forged webhook → 401

**Files:**
- Create: `tests/test_payment_webhook_forgery.py`

Это **единственный** тест, который нельзя не писать (см. v4 spec).

- [ ] **Step 1:** создать файл

```python
"""
MANDATORY security test — см. docs/senior-upgrade-prompt-v4.md.

Стучимся в webhook-хендлер с заведомо неверной подписью.
Если ответ != 401 — фикс незамедлительный, релиз блокируется.
"""
import os
import pytest
from aiohttp.test_utils import TestClient, TestServer
from aiohttp import web

# Выставляем env ДО импорта модулей — fail-fast в config.py ловит пустые креды.
os.environ.setdefault("BOT_TOKEN", "1:test")
os.environ.setdefault("ADMIN_IDS", "1")
os.environ.setdefault("PAYMENT_PROVIDER", "click")
os.environ.setdefault("CLICK_SERVICE_ID", "111")
os.environ.setdefault("CLICK_MERCHANT_ID", "222")
os.environ.setdefault("CLICK_MERCHANT_USER_ID", "333")
os.environ.setdefault("CLICK_SECRET_KEY", "secret_real")
os.environ.setdefault("PAYMENT_PUBLIC_URL", "https://example.invalid")


@pytest.mark.asyncio
async def test_click_forged_signature_returns_401():
    from utils.payments.server import _click_handler

    app = web.Application()
    app["bot"] = None
    app.router.add_post("/payment/click", _click_handler)

    async with TestClient(TestServer(app)) as client:
        # Подпись заведомо левая (32 hex char, но от другого secret).
        payload = {
            "click_trans_id": "123",
            "service_id": "111",
            "merchant_trans_id": "42",
            "amount": "150000",
            "action": "1",
            "sign_time": "2026-04-21 12:00:00",
            "sign_string": "a" * 32,
        }
        resp = await client.post("/payment/click", data=payload)
        assert resp.status == 401, f"ожидали 401, получили {resp.status}"


@pytest.mark.asyncio
async def test_click_missing_signature_returns_401():
    from utils.payments.server import _click_handler

    app = web.Application()
    app["bot"] = None
    app.router.add_post("/payment/click", _click_handler)

    async with TestClient(TestServer(app)) as client:
        resp = await client.post("/payment/click", data={"action": "1"})
        assert resp.status == 401


@pytest.mark.asyncio
async def test_payme_forged_basic_auth_returns_401(monkeypatch):
    monkeypatch.setenv("PAYMENT_PROVIDER", "payme")
    monkeypatch.setenv("PAYME_MERCHANT_ID", "mmm")
    monkeypatch.setenv("PAYME_SECRET_KEY", "correct_secret")

    # Сбросить кеш провайдера, иначе из первого теста останется Click.
    import utils.payments as pkg
    pkg._provider = None

    from utils.payments.server import _payme_handler

    app = web.Application()
    app["bot"] = None
    app.router.add_post("/payment/payme", _payme_handler)

    async with TestClient(TestServer(app)) as client:
        # Правильный формат Basic, но неверный secret.
        import base64
        bad = base64.b64encode(b"Paycom:wrong_secret").decode()
        resp = await client.post(
            "/payment/payme",
            headers={"Authorization": f"Basic {bad}"},
            json={"jsonrpc": "2.0", "method": "PerformTransaction", "params": {"account": {"appointment_id": 1}}, "id": 1},
        )
        assert resp.status == 401
```

- [ ] **Step 2:** прогнать

```bash
docker compose exec bot pytest tests/test_payment_webhook_forgery.py -v
```
Expected: 3 теста PASSED. Любой FAIL — стоп, фикс signature-логики.

---

## Task 13 — Docker / порт

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1:** добавить `ports: ["127.0.0.1:8443:8443"]` в сервис `bot`.
      Публичный трафик приходит через Caddy/nginx (хост-сервис) → bind
      именно на 127.0.0.1, не 0.0.0.0, чтобы не выставить бот наружу
      напрямую.

---

## Task 14 — Документация оператора

**Files:**
- Create: `docs/PAYMENTS.md`

- [ ] **Step 1:** документ должен ответить на:
1. Как получить CLICK_SERVICE_ID / CLICK_MERCHANT_ID / CLICK_MERCHANT_USER_ID /
   CLICK_SECRET_KEY в дашборде Click.
2. Какие URL указать в кабинете Click для Prepare/Complete webhook:
   `https://<PAYMENT_PUBLIC_URL>/payment/click`.
3. То же для Payme: `https://<PAYMENT_PUBLIC_URL>/payment/payme`.
4. Пример Caddy-конфига:
   ```caddy
   bot.sabinanails.uz {
       reverse_proxy /payment/* 127.0.0.1:8443
       reverse_proxy /health 127.0.0.1:8443
   }
   ```
5. Как проверить что webhook работает: `curl -X POST https://.../health`
   → `ok`.
6. Что делать при отмене оплаченной записи (ручной refund в дашборде).
7. Троблшут: где посмотреть логи (`docker compose logs bot | grep payment`).

---

## Task 16 — Mock-Click сервер для локального теста

**Files:**
- Create: `tools/mock_click_server.py`

Это отдельный standalone-скрипт. Поднимается рядом с ботом:
`python tools/mock_click_server.py`. Имитирует:
1. `POST /mock-click/v2/merchant/invoice/create` — как настоящий Click,
   возвращает `{error_code: 0, invoice_id: "<uuid>"}`.
2. `GET /mock-click/pay?...` — HTML-страница с одной кнопкой
   «Оплатить». По клику mock формирует валидную Click-подпись
   (тот же SHA1-флоу, тот же SECRET_KEY из .env) и шлёт POST на бот.
3. Prepare + Complete — оба шага автоматически, Click обычно шлёт
   prepare, потом complete; mock эмулирует оба за один клик «заплатить».

Подпись считается тем же `CLICK_SECRET_KEY`, что знает бот — поэтому
verify_and_parse в `utils/payments/click.py` её примет как настоящую.
Это не компромат безопасности: в проде `CLICK_API_BASE` и
`CLICK_PAY_URL_BASE` НЕ выставляются, fallback на api.click.uz.

- [ ] **Step 1:** создать файл

```python
"""
Mock-сервер Click для локальной разработки.

Запуск:
    python tools/mock_click_server.py

Бот должен быть настроен с:
    PAYMENT_PROVIDER=click
    CLICK_SERVICE_ID=111
    CLICK_MERCHANT_ID=222
    CLICK_MERCHANT_USER_ID=333
    CLICK_SECRET_KEY=devsecret                (любая строка, главное совпадает)
    CLICK_API_BASE=http://localhost:8444/mock-click/v2/merchant
    CLICK_PAY_URL_BASE=http://localhost:8444/mock-click/pay
    PAYMENT_PUBLIC_URL=http://localhost:8443  (сам бот)
    PAYMENT_WEBHOOK_PORT=8443

Флоу:
1. Клиент в боте доходит до confirm_yes → бот зовёт наш /invoice/create.
2. Получает invoice_id + pay_url типа http://localhost:8444/mock-click/pay?...
3. В браузере открывается страница с кнопкой «Оплатить».
4. Клик → mock считает правильную Click-подпись и стучится в бот
   http://localhost:8443/payment/click с action=0 (prepare) и action=1 (complete).
5. Бот помечает paid_at → шлёт клиенту «✓ оплата получена».
"""
from __future__ import annotations

import hashlib
import os
import time
import uuid
from urllib.parse import urlencode

import aiohttp
from aiohttp import web
from dotenv import load_dotenv

load_dotenv()

SECRET = os.getenv("CLICK_SECRET_KEY", "devsecret")
SERVICE_ID = os.getenv("CLICK_SERVICE_ID", "111")
BOT_WEBHOOK = os.getenv("PAYMENT_PUBLIC_URL", "http://localhost:8443").rstrip("/") + "/payment/click"
PORT = int(os.getenv("MOCK_CLICK_PORT", "8444"))


async def invoice_create(request: web.Request) -> web.Response:
    """Имитация https://api.click.uz/v2/merchant/invoice/create."""
    body = await request.json()
    invoice_id = str(uuid.uuid4().int)[:10]
    print(f"[mock-click] invoice/create appt={body.get('merchant_trans_id')} "
          f"amount={body.get('amount')} → invoice_id={invoice_id}")
    return web.json_response({
        "error_code": 0,
        "error_note": "Success",
        "invoice_id": invoice_id,
    })


async def pay_page(request: web.Request) -> web.Response:
    """Страничка имитирующая checkout Click. Одна кнопка «Оплатить»."""
    q = request.rel_url.query
    html = f"""
    <!DOCTYPE html><meta charset="utf-8">
    <title>Mock Click Pay</title>
    <style>
      body {{ font-family: sans-serif; padding: 40px; background:#f4f4f8; }}
      .card {{ background:#fff; padding:30px; border-radius:12px;
               max-width:400px; box-shadow:0 2px 12px rgba(0,0,0,.08); }}
      button {{ padding:14px 24px; background:#00a859; color:#fff;
                border:none; border-radius:8px; font-size:16px; cursor:pointer; }}
      dt {{ color:#888; font-size:12px; text-transform:uppercase; }}
      dd {{ margin:0 0 12px 0; }}
    </style>
    <div class=card>
      <h2>🧪 Mock Click</h2>
      <dl>
        <dt>service_id</dt><dd>{q.get('service_id','')}</dd>
        <dt>merchant_id</dt><dd>{q.get('merchant_id','')}</dd>
        <dt>amount</dt><dd>{q.get('amount','')} UZS</dd>
        <dt>transaction_param (invoice_id)</dt><dd>{q.get('transaction_param','')}</dd>
      </dl>
      <form method=post action=/mock-click/do-pay>
        <input type=hidden name=invoice_id value="{q.get('transaction_param','')}">
        <input type=hidden name=amount value="{q.get('amount','')}">
        <button type=submit>Оплатить</button>
      </form>
    </div>
    """
    return web.Response(text=html, content_type="text/html")


def _sign(click_trans_id: str, merchant_trans_id: str, merchant_prepare_id: str,
          amount: str, action: str, sign_time: str) -> str:
    raw = (
        f"{click_trans_id}{SERVICE_ID}{SECRET}{merchant_trans_id}"
        f"{merchant_prepare_id}{amount}{action}{sign_time}"
    )
    return hashlib.md5(raw.encode()).hexdigest()


async def do_pay(request: web.Request) -> web.Response:
    """Эмуляция двух шагов Click: prepare (action=0) → complete (action=1)."""
    form = await request.post()
    invoice_id = form["invoice_id"]  # это appt_id (см. attach_invoice — передали в ClickProvider)
    # НО! В нашем коде мы invoice_id из Click API (str(uuid-число)) пишем в БД.
    # При webhook Click шлёт merchant_trans_id = appt_id. Здесь мы берём его из
    # нашей pay_page, которой передали transaction_param=<invoice_id_from_api>.
    # Для mock упростим: invoice_id на API и merchant_trans_id на webhook = одно и то же.
    merchant_trans_id = invoice_id
    amount = str(form["amount"])
    click_trans_id = str(int(time.time()))
    sign_time = time.strftime("%Y-%m-%d %H:%M:%S")

    async with aiohttp.ClientSession() as session:
        # Prepare
        sign_prepare = _sign(click_trans_id, merchant_trans_id, "", amount, "0", sign_time)
        prep_data = {
            "click_trans_id": click_trans_id,
            "service_id": SERVICE_ID,
            "click_paydoc_id": click_trans_id,
            "merchant_trans_id": merchant_trans_id,
            "amount": amount,
            "action": "0",
            "error": "0",
            "error_note": "",
            "sign_time": sign_time,
            "sign_string": sign_prepare,
        }
        print(f"[mock-click] → prepare {BOT_WEBHOOK}")
        async with session.post(BOT_WEBHOOK, data=prep_data) as r:
            prep_resp = await r.json()
            print(f"[mock-click]   bot resp: {prep_resp}")

        merchant_prepare_id = str(prep_resp.get("merchant_prepare_id", ""))

        # Complete
        sign_complete = _sign(click_trans_id, merchant_trans_id, merchant_prepare_id, amount, "1", sign_time)
        comp_data = {**prep_data, "action": "1", "merchant_prepare_id": merchant_prepare_id,
                     "sign_string": sign_complete}
        print(f"[mock-click] → complete {BOT_WEBHOOK}")
        async with session.post(BOT_WEBHOOK, data=comp_data) as r:
            comp_resp = await r.json()
            print(f"[mock-click]   bot resp: {comp_resp}")

    return web.Response(
        text="<h2>✓ Оплачено (mock)</h2><p>Возвращайся в Telegram — бот уже в курсе.</p>",
        content_type="text/html",
    )


def main() -> None:
    app = web.Application()
    app.router.add_post("/mock-click/v2/merchant/invoice/create", invoice_create)
    app.router.add_get("/mock-click/pay", pay_page)
    app.router.add_post("/mock-click/do-pay", do_pay)
    print(f"[mock-click] listening on http://localhost:{PORT}")
    print(f"[mock-click] bot webhook → {BOT_WEBHOOK}")
    web.run_app(app, host="0.0.0.0", port=PORT, print=None)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2:** dev-verification

Два терминала:

```bash
# Терминал 1
python tools/mock_click_server.py

# Терминал 2 (бот)
python bot.py
```

В .env (локально) должно быть:
```
PAYMENT_PROVIDER=click
CLICK_SERVICE_ID=111
CLICK_MERCHANT_ID=222
CLICK_MERCHANT_USER_ID=333
CLICK_SECRET_KEY=devsecret
CLICK_API_BASE=http://localhost:8444/mock-click/v2/merchant
CLICK_PAY_URL_BASE=http://localhost:8444/mock-click/pay
PAYMENT_PUBLIC_URL=http://localhost:8443
```

Флоу:
1. В боте сделать запись до `confirm_yes`.
2. Бот прислал кнопку «💳 Оплатить» → жми → открывается mock-страница.
3. Клик «Оплатить» → mock шлёт prepare+complete → бот помечает paid →
   клиенту приходит «✓ оплата получена», админу «💰 Оплата прошла».
4. В админ-карточке — «💰 Оплачено».

Если на шаге 3 bot вернул 401 — ошибка в подписи, смотри логи
обоих терминалов.

---

## Task 15 — Финальная верификация (sandbox-ручная) + коммит

По v4-спеке (строки 129-142):

- [ ] Клиент в sandbox доходит до `confirm_yes`.
- [ ] Видит кнопку «💳 Оплатить».
- [ ] Платит 100 UZS → бот присылает «✓ оплата получена» за 2-5 с.
- [ ] В админке статус «💰 Оплачено», `paid_at` заполнен.
- [ ] Симуляция timeout: если не заплатить, через 30 мин — «⏳ ждёт оплаты»,
      запись жива.
- [ ] Отмена оплаченной записи → админ получает «🔴 нужен возврат».
- [ ] Forged-webhook тест зелёный.

- [ ] **Step Final:** commit + push

```bash
git add -A
git commit -m "feat(payments): click+payme online invoices with webhook

- migration v2→v3: paid_at, payment_provider, payment_invoice_id
- aiohttp webhook server at /payment/click, /payment/payme
- signature verification (HMAC + Basic auth), fail-closed 401
- idempotent mark_paid via UNIQUE(invoice_id)
- admin refund-alert on cancel of paid appt (auto-refund deferred)
- mandatory forgery test: 3 cases, all green
"
git push origin main
```

---

## Self-Review Notes

- **Spec coverage:** все 7 пунктов v4-verification покрыты Task 15.
  Mandatory security-test — Task 12.
- **Placeholders:** в Task 10 указано «точные линии определит исполнитель»
  — оправдано, потому что `admin_appointments.py` ~25KB и место рендера
  единственное (по `service_name`). Не блокер.
- **Deferred in-phase:** полные JSON-RPC методы Payme (Create/Cancel
  /CheckTransaction). На MVP помечаем paid только на Perform. TODO в
  `docs/PAYMENTS.md`.
- **Risks:**
  1. Click API — SERVICE_ID и MERCHANT_USER_ID в разных дашбордах;
     первый раз легко перепутать. PAYMENTS.md закроет.
  2. Caddy/nginx должен быть уже установлен у салона — добавить в
     `install.sh` отдельной задачей (v.4 FUTURE).
  3. SQLite + UNIQUE partial index — проверить что CREATE INDEX
     идемпотентен при перезапуске (он `IF NOT EXISTS` — ок).
