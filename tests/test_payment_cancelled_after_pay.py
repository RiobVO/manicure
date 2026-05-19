"""
Регрессионный тест: cancel-after-pay race.

Сценарий: клиент создал запись → получил платёжную ссылку → отменил запись →
открыл старое сообщение, перешёл по ссылке, оплатил. Webhook от провайдера
ДОЛЖЕН получить от нас error-ответ, иначе провайдер считает оплату принятой
и списывает с клиента деньги за услугу, которой не будет.

До фикса сервер отвечал Success в обоих случаях (Click error=0, Payme
result.state=2) — реальный риск денег клиента.
"""
from __future__ import annotations

# ─── ENV до импортов проекта ─────────────────────────────────────────────────
import os

os.environ.setdefault("BOT_TOKEN", "1:test")
os.environ.setdefault("ADMIN_IDS", "1")
os.environ.setdefault("PAYMENT_PROVIDER", "click")
os.environ.setdefault("CLICK_SERVICE_ID", "111")
os.environ.setdefault("CLICK_MERCHANT_ID", "222")
os.environ.setdefault("CLICK_MERCHANT_USER_ID", "333")
os.environ.setdefault("CLICK_SECRET_KEY", "secret_real")
os.environ.setdefault("PAYMENT_PUBLIC_URL", "https://example.invalid")

import base64
import hashlib
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import config
import utils.payments as payments_pkg
import utils.payments.click as click_mod
import utils.payments.payme as payme_mod
from utils.payments.server import _click_handler, _payme_handler


SECRET = "secret_real"
PAYME_SECRET = "payme_real_secret"


def _make_app() -> web.Application:
    app = web.Application()
    # Bot нужен только при успешной оплате (_notify_paid). В cancelled-тестах
    # до этого не доходит — отказ возвращается из mark_paid/verify_and_parse.
    app["bot"] = None
    app.router.add_post("/payment/click", _click_handler)
    app.router.add_post("/payment/payme", _payme_handler)
    return app


def _enable_click(monkeypatch) -> None:
    monkeypatch.setattr(config, "PAYMENT_PROVIDER", "click", raising=False)
    monkeypatch.setattr(payments_pkg, "PAYMENT_PROVIDER", "click", raising=False)
    monkeypatch.setattr(config, "CLICK_SECRET_KEY", SECRET, raising=False)
    monkeypatch.setattr(click_mod, "CLICK_SECRET_KEY", SECRET, raising=False)
    payments_pkg._reset_for_tests()


def _enable_payme(monkeypatch) -> None:
    monkeypatch.setattr(config, "PAYMENT_PROVIDER", "payme", raising=False)
    monkeypatch.setattr(payments_pkg, "PAYMENT_PROVIDER", "payme", raising=False)
    monkeypatch.setattr(config, "PAYME_MERCHANT_ID", "merchant_xyz", raising=False)
    monkeypatch.setattr(config, "PAYME_SECRET_KEY", PAYME_SECRET, raising=False)
    monkeypatch.setattr(payme_mod, "PAYME_MERCHANT_ID", "merchant_xyz", raising=False)
    monkeypatch.setattr(payme_mod, "PAYME_SECRET_KEY", PAYME_SECRET, raising=False)
    payments_pkg._reset_for_tests()


def _click_signed_body(appt_id: int, amount: int) -> str:
    """Собрать валидно подписанный Complete-webhook Click'а."""
    click_trans_id = "9999"
    service_id = "111"
    merchant_trans_id = str(appt_id)
    merchant_prepare_id = ""
    action = "1"
    sign_time = "2026-04-22 10:00:00"
    raw = (
        f"{click_trans_id}{service_id}{SECRET}{merchant_trans_id}"
        f"{merchant_prepare_id}{amount}{action}{sign_time}"
    )
    sign_string = hashlib.md5(raw.encode()).hexdigest()
    return (
        f"click_trans_id={click_trans_id}"
        f"&service_id={service_id}"
        f"&merchant_trans_id={merchant_trans_id}"
        f"&merchant_prepare_id={merchant_prepare_id}"
        f"&amount={amount}"
        f"&action={action}"
        f"&sign_time={sign_time.replace(' ', '+')}"
        f"&sign_string={sign_string}"
    )


async def _seed_paid_flow(seed_master, seed_service, cancel: bool) -> int:
    """
    Создаёт запись + привязывает invoice. Если cancel=True — отменяет.
    Возвращает appt_id.
    """
    from db import create_appointment, cancel_appointment_by_client
    from db.payments import attach_invoice

    master_id = await seed_master(name="Анна")
    service_id = await seed_service(name="Маникюр", price=150000, duration=60)

    appt_id = await create_appointment(
        user_id=777, name="Клиент", phone="+998900000000",
        service_id=service_id, service_name="Маникюр",
        service_duration=60, service_price=150000,
        date="2099-01-01", time="10:00", master_id=master_id,
    )
    await attach_invoice(
        appt_id, provider="click", invoice_id=str(appt_id),
        pay_url="https://pay.test/1",
    )
    if cancel:
        await cancel_appointment_by_client(appt_id, user_id=777, reason="test")
    return appt_id


# ─── Click: cancel-after-pay → error=-9 ──────────────────────────────────────

async def test_click_cancel_after_pay_returns_error_9(
    monkeypatch, fresh_db, seed_master, seed_service,
):
    """
    Click Complete webhook приходит ПОСЛЕ отмены записи → сервер обязан
    ответить error=-9 (Transaction cancelled), чтобы Click вернул деньги.
    """
    _enable_click(monkeypatch)
    appt_id = await _seed_paid_flow(seed_master, seed_service, cancel=True)
    body = _click_signed_body(appt_id, amount=150000)

    async with TestClient(TestServer(_make_app())) as client:
        resp = await client.post(
            "/payment/click", data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert resp.status == 200
        payload = await resp.json()
        assert payload["error"] == -9, (
            f"cancelled запись должна давать Click error=-9, получили {payload}"
        )

    payments_pkg._reset_for_tests()


# ─── Click: happy path (запись активна) → error=0 ────────────────────────────

async def test_click_active_appointment_returns_error_0(
    monkeypatch, fresh_db, seed_master, seed_service,
):
    """Негативный контроль: активная запись → error=0 Success."""
    _enable_click(monkeypatch)
    appt_id = await _seed_paid_flow(seed_master, seed_service, cancel=False)
    body = _click_signed_body(appt_id, amount=150000)

    app = _make_app()
    # _notify_paid стреляет create_task — подменим бота на заглушку,
    # чтобы задача не падала и не забивала лог.
    class _DummyBot:
        async def send_message(self, *a, **kw): pass
    app["bot"] = _DummyBot()

    async with TestClient(TestServer(app)) as client:
        resp = await client.post(
            "/payment/click", data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert resp.status == 200
        payload = await resp.json()
        assert payload["error"] == 0, payload

    payments_pkg._reset_for_tests()


# ─── Payme: CheckPerformTransaction на отменённую запись → -31008 ────────────

async def test_payme_check_on_cancelled_returns_31008(
    monkeypatch, fresh_db, seed_master, seed_service,
):
    """
    Первая линия обороны: verify_and_parse для CheckPerformTransaction
    должен отказывать на отменённой записи, иначе Payme allow'ит оплату.
    """
    _enable_payme(monkeypatch)

    from db import create_appointment, cancel_appointment_by_client
    from db.payments import attach_invoice

    master_id = await seed_master(name="Катя")
    service_id = await seed_service(name="Педикюр", price=200000, duration=90)
    appt_id = await create_appointment(
        user_id=888, name="Клиент2", phone="+998900000001",
        service_id=service_id, service_name="Педикюр",
        service_duration=90, service_price=200000,
        date="2099-02-02", time="11:00", master_id=master_id,
    )
    await attach_invoice(
        appt_id, provider="payme", invoice_id=str(appt_id),
        pay_url="https://checkout.paycom.uz/xxx",
    )
    await cancel_appointment_by_client(appt_id, user_id=888, reason="test")

    auth = base64.b64encode(f"Paycom:{PAYME_SECRET}".encode()).decode()
    body = {
        "jsonrpc": "2.0",
        "id": 42,
        "method": "CheckPerformTransaction",
        "params": {
            "amount": 200000 * 100,  # тийины
            "account": {"appointment_id": str(appt_id)},
        },
    }

    async with TestClient(TestServer(_make_app())) as client:
        resp = await client.post(
            "/payment/payme", data=json.dumps(body),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Basic {auth}",
            },
        )
        assert resp.status == 200
        payload = await resp.json()
        assert "error" in payload, (
            f"Payme Check на cancelled должен быть error, получили {payload}"
        )
        assert payload["error"]["code"] == -31008, payload

    payments_pkg._reset_for_tests()


# ─── Click: duplicate (уже оплачено) → error=-4 ─────────────────────────────

async def test_click_duplicate_after_pay_returns_error_4(
    monkeypatch, fresh_db, seed_master, seed_service,
):
    """
    Клиент тапнул старую pay-ссылку после успешной оплаты → mark_paid видит
    paid_at и возвращает 'duplicate'. Сервер должен ответить -4 «Already paid»,
    чтобы Click откатил повторное списание.
    """
    _enable_click(monkeypatch)

    from db import create_appointment
    from db.payments import attach_invoice, mark_paid

    master_id = await seed_master(name="Оля")
    service_id = await seed_service(name="Маникюр", price=150000, duration=60)
    appt_id = await create_appointment(
        user_id=555, name="Повторятель", phone="+998900000003",
        service_id=service_id, service_name="Маникюр",
        service_duration=60, service_price=150000,
        date="2099-05-05", time="09:00", master_id=master_id,
    )
    await attach_invoice(
        appt_id, provider="click", invoice_id=str(appt_id),
        pay_url="https://pay.test/dup",
    )
    # Первый платёж — ставим paid_at напрямую.
    status, _ = await mark_paid("click", invoice_id=str(appt_id))
    assert status == "paid"

    # Второй webhook — клиент тапнул старую ссылку.
    body = _click_signed_body(appt_id, amount=150000)
    async with TestClient(TestServer(_make_app())) as client:
        resp = await client.post(
            "/payment/click", data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert resp.status == 200
        payload = await resp.json()
        assert payload["error"] == -4, (
            f"duplicate должен давать -4 'Already paid', получили {payload}"
        )

    payments_pkg._reset_for_tests()


# ─── Payme: defence-in-depth на PerformTransaction → -31008 ──────────────────

async def test_payme_perform_on_cancelled_returns_31008(
    monkeypatch, fresh_db, seed_master, seed_service,
):
    """
    Если cancel произошёл между Check и Perform (race), Perform-ответ
    всё равно должен быть error, а не state:2 (оплачено).
    """
    _enable_payme(monkeypatch)

    from db import create_appointment, cancel_appointment_by_client
    from db.payments import attach_invoice

    master_id = await seed_master(name="Лена")
    service_id = await seed_service(name="Маникюр", price=180000, duration=60)
    appt_id = await create_appointment(
        user_id=999, name="Клиент3", phone="+998900000002",
        service_id=service_id, service_name="Маникюр",
        service_duration=60, service_price=180000,
        date="2099-03-03", time="12:00", master_id=master_id,
    )
    await attach_invoice(
        appt_id, provider="payme", invoice_id=str(appt_id),
        pay_url="https://checkout.paycom.uz/yyy",
    )
    await cancel_appointment_by_client(appt_id, user_id=999, reason="test")

    auth = base64.b64encode(f"Paycom:{PAYME_SECRET}".encode()).decode()
    body = {
        "jsonrpc": "2.0",
        "id": 43,
        "method": "PerformTransaction",
        "params": {
            "amount": 180000 * 100,
            "account": {"appointment_id": str(appt_id)},
        },
    }

    async with TestClient(TestServer(_make_app())) as client:
        resp = await client.post(
            "/payment/payme", data=json.dumps(body),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Basic {auth}",
            },
        )
        assert resp.status == 200
        payload = await resp.json()
        assert "error" in payload, (
            f"Payme Perform на cancelled должен быть error, получили {payload}"
        )
        assert payload["error"]["code"] == -31008, payload
        # И state:2 не должно быть
        assert "result" not in payload or payload.get("result", {}).get("state") != 2

    payments_pkg._reset_for_tests()
