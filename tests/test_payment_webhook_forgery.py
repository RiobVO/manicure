"""
Phase 1 v.4 — обязательный security-тест платёжных webhook'ов.

Три кейса, все требуют HTTP 401:
  1. Click: подделанный sign_string (32 hex, но не от нашего SECRET).
  2. Click: sign_string отсутствует вообще.
  3. Payme: Basic auth от неправильного SECRET_KEY.

Замечание по env: conftest.py импортирует config ДО этого файла, поэтому
config.PAYMENT_PROVIDER уже зафиксирован ('none', если в .env не иное).
Переключение провайдера внутри теста делаем через monkeypatch на модули
(config + utils.payments.click/payme) плюс payments._reset_for_tests() —
чтобы фабрика переинициализировала провайдер с нужным name.
"""
from __future__ import annotations

# ─── ENV до любых импортов проекта ───────────────────────────────────────────
import os

os.environ.setdefault("BOT_TOKEN", "1:test")
os.environ.setdefault("ADMIN_IDS", "1")
os.environ.setdefault("PAYMENT_PROVIDER", "click")
os.environ.setdefault("CLICK_SERVICE_ID", "111")
os.environ.setdefault("CLICK_MERCHANT_ID", "222")
os.environ.setdefault("CLICK_MERCHANT_USER_ID", "333")
os.environ.setdefault("CLICK_SECRET_KEY", "secret_real")
os.environ.setdefault("PAYMENT_PUBLIC_URL", "https://example.invalid")

# ─── Импорты ─────────────────────────────────────────────────────────────────
import base64

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import config
import utils.payments as payments_pkg
import utils.payments.click as click_mod
import utils.payments.payme as payme_mod
from utils.payments.server import _click_handler, _payme_handler


def _make_app() -> web.Application:
    """Одноразовое aiohttp-приложение с двумя нашими хендлерами.
    app['bot'] до mark_paid не используется; forgery-тесты возвращают 401
    до этого шага, поэтому None безопасен."""
    app = web.Application()
    app["bot"] = None
    app.router.add_post("/payment/click", _click_handler)
    app.router.add_post("/payment/payme", _payme_handler)
    return app


def _enable_click(monkeypatch) -> None:
    """Переключить фабрику провайдеров на Click + прошить креды в модуль click."""
    monkeypatch.setattr(config, "PAYMENT_PROVIDER", "click", raising=False)
    monkeypatch.setattr(payments_pkg, "PAYMENT_PROVIDER", "click", raising=False)
    monkeypatch.setattr(config, "CLICK_SECRET_KEY", "secret_real", raising=False)
    monkeypatch.setattr(click_mod, "CLICK_SECRET_KEY", "secret_real", raising=False)
    payments_pkg._reset_for_tests()


def _enable_payme(monkeypatch) -> None:
    """Переключить фабрику на Payme + прошить креды в модуль payme."""
    monkeypatch.setattr(config, "PAYMENT_PROVIDER", "payme", raising=False)
    monkeypatch.setattr(payments_pkg, "PAYMENT_PROVIDER", "payme", raising=False)
    monkeypatch.setattr(config, "PAYME_MERCHANT_ID", "merchant_xyz", raising=False)
    monkeypatch.setattr(config, "PAYME_SECRET_KEY", "real_secret", raising=False)
    monkeypatch.setattr(payme_mod, "PAYME_MERCHANT_ID", "merchant_xyz", raising=False)
    monkeypatch.setattr(payme_mod, "PAYME_SECRET_KEY", "real_secret", raising=False)
    payments_pkg._reset_for_tests()


# ─── Click: подделанная подпись ──────────────────────────────────────────────

async def test_click_forged_signature_returns_401(monkeypatch):
    """32 hex-символа, но вычисленные НЕ от CLICK_SECRET_KEY='secret_real'."""
    _enable_click(monkeypatch)

    body = (
        "click_trans_id=9999"
        "&service_id=111"
        "&merchant_trans_id=42"
        "&merchant_prepare_id="
        "&amount=150000"
        "&action=1"
        "&sign_time=2026-04-21+10:00:00"
        "&sign_string=" + ("a" * 32)  # длина корректная, подпись левая
    )

    async with TestClient(TestServer(_make_app())) as client:
        resp = await client.post(
            "/payment/click",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert resp.status == 401, (
            f"forged click signature должен давать 401, получили {resp.status}"
        )

    payments_pkg._reset_for_tests()


# ─── Click: отсутствие sign_string ───────────────────────────────────────────

async def test_click_missing_signature_returns_401(monkeypatch):
    """Поле sign_string отсутствует в теле целиком."""
    _enable_click(monkeypatch)

    body = "action=1"  # только action, ничего больше

    async with TestClient(TestServer(_make_app())) as client:
        resp = await client.post(
            "/payment/click",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert resp.status == 401, (
            f"missing sign_string должен давать 401, получили {resp.status}"
        )

    payments_pkg._reset_for_tests()


# ─── Payme: подделанный Basic auth ───────────────────────────────────────────

async def test_payme_forged_basic_auth_returns_401(monkeypatch):
    """Authorization: Basic base64('Paycom:wrong_secret') — не наш ключ."""
    _enable_payme(monkeypatch)

    wrong = base64.b64encode(b"Paycom:wrong_secret").decode()
    body = '{"jsonrpc":"2.0","id":1,"method":"PerformTransaction","params":{}}'

    async with TestClient(TestServer(_make_app())) as client:
        resp = await client.post(
            "/payment/payme",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Basic {wrong}",
            },
        )
        assert resp.status == 401, (
            f"forged payme basic auth должен давать 401, получили {resp.status}"
        )

    payments_pkg._reset_for_tests()
