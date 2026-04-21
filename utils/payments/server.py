"""
aiohttp-сервер приёма webhook от Click/Payme. Работает В ТОМ ЖЕ процессе
что и polling — стартует отдельной task в bot.py::main. Без лишних
контейнеров: solo-dev владеет одним python-процессом, не двумя.

Безопасность (v.4 Phase 1 требования):
  • Подпись/Basic auth проверяются ДО обработки тела (в verify_and_parse).
  • Rate-limit: 60 req/min на IP (in-memory sliding window). Для одного VPS
    достаточно; распределённый rate-limit — YAGNI.
  • Fail-closed: любое непредусмотренное исключение → 401. Провайдер
    ретранет, если ответ 5xx — это корректно; лучше молчать, чем marked-paid
    по багу.
  • Idempotency: mark_paid() на уровне БД не переписывает paid_at.
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
    """Простой sliding-window 60 секунд. Чистим устаревшие запросы на месте."""
    now = time.time()
    q = _rate_log[ip]
    while q and q[0] < now - 60:
        q.popleft()
    if len(q) >= _RATE_LIMIT_PER_MIN:
        return True
    q.append(now)
    return False


async def _notify_paid(bot: Bot, appt_id: int) -> None:
    """После успешной оплаты: клиенту — ✓, админам — 💰. Обе ошибки не фатальны."""
    state = await get_payment_state(appt_id)
    if not state:
        logger.warning("_notify_paid: состояние не найдено для appt=%s", appt_id)
        return
    try:
        await bot.send_message(
            state["user_id"],
            "<i>✓ оплата получена.</i>\n<i>жду тебя.</i>",
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.warning("не доставил клиенту подтверждение оплаты user=%s: %s",
                       state["user_id"], exc)

    try:
        from utils.notifications import admin_dismiss_kb
        price_fmt = f"{state['service_price']:,}".replace(",", " ")
        await broadcast_to_admins(
            bot,
            f"💰 <b>Оплата прошла</b>\n"
            f"{state['date']} · {state['time']} — {state['name']}\n"
            f"{state['service_name']} · {price_fmt} UZS",
            reply_markup=admin_dismiss_kb(),
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

    # Prepare-шаг Click разобран отдельно: paid не ставим, возвращаем ack
    # с merchant_prepare_id = наш appt_id.
    try:
        appt_id_str = await provider.verify_and_parse(dict(request.headers), raw)
    except _ClickPrepare as prep:
        return web.json_response({
            "click_trans_id": int(prep.click_trans_id) if prep.click_trans_id.isdigit() else 0,
            "merchant_trans_id": prep.merchant_trans_id,
            "merchant_prepare_id": int(prep.merchant_trans_id) if prep.merchant_trans_id.isdigit() else 0,
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
        logger.exception("click webhook: unexpected error → fail-closed 401")
        return web.Response(status=401, text="unauthorized")

    # Complete: помечаем paid. Идемпотентно — повторный webhook не переписывает.
    # В БД payment_invoice_id = str(appt_id) = то, что Click шлёт как merchant_trans_id.
    paid_appt = await mark_paid("click", invoice_id=appt_id_str)
    if paid_appt is not None:
        bot: Bot = request.app["bot"]
        asyncio.create_task(_notify_paid(bot, paid_appt))

    # Click требует merchant_confirm_id в ответ на Complete.
    appt_id_int = int(appt_id_str) if appt_id_str.isdigit() else 0
    return web.json_response({
        "click_trans_id": 0,  # настоящий id не нужен Click'у в ответе
        "merchant_trans_id": appt_id_str,
        "merchant_confirm_id": appt_id_int,
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
        # Все методы кроме Perform — шаблонный ack. На MVP хватает: Payme
        # не блокирует платёж при упрощённом CheckPerform/Create.
        return web.json_response(_payme_ack(non))
    except PermissionError as exc:
        logger.warning("payme webhook 401 from %s: %s", ip, exc)
        return web.Response(status=401, text="unauthorized")
    except ValueError as exc:
        logger.warning("payme webhook 400 from %s: %s", ip, exc)
        return web.Response(status=400, text="bad request")
    except Exception:
        logger.exception("payme webhook: unexpected error → fail-closed 401")
        return web.Response(status=401, text="unauthorized")

    paid_appt = await mark_paid("payme", invoice_id=appt_id_str)
    if paid_appt is not None:
        bot: Bot = request.app["bot"]
        asyncio.create_task(_notify_paid(bot, paid_appt))

    # Ответ PerformTransaction согласно спеке Payme.
    try:
        body = json.loads(raw.decode("utf-8"))
        rpc_id = body.get("id")
    except Exception:
        rpc_id = None
    appt_id_int = int(appt_id_str) if appt_id_str.isdigit() else 0
    return web.json_response({
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {
            "transaction": appt_id_str,
            "perform_time": int(time.time() * 1000),
            "state": 2,
        },
    })


def _payme_ack(non: _PaymeNonPerform) -> dict:
    """Минимальный JSON-RPC ответ для не-Perform методов Payme.
    CheckPerformTransaction → allow:true (предполагаем, что запись валидна).
    CreateTransaction → state:1 + transaction id.
    Остальные (Cancel/CheckTransaction/GetStatement) — state:1 заглушкой.
    FUTURE: полноценная реализация при жалобах в проде."""
    if non.method == "CheckPerformTransaction":
        return {"jsonrpc": "2.0", "id": non.rpc_id, "result": {"allow": True}}
    if non.method == "CreateTransaction":
        return {"jsonrpc": "2.0", "id": non.rpc_id, "result": {
            "transaction": str(non.params.get("id", "")),
            "create_time": int(time.time() * 1000),
            "state": 1,
        }}
    return {"jsonrpc": "2.0", "id": non.rpc_id, "result": {"state": 1}}


async def _health(_request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def start_webhook_server(bot: Bot) -> web.AppRunner:
    """
    Поднять aiohttp на PAYMENT_WEBHOOK_PORT. Bind на 0.0.0.0 внутри контейнера —
    публичный трафик ограничен docker-compose ports: 127.0.0.1:PORT:PORT.
    """
    app = web.Application()
    app["bot"] = bot
    app.router.add_post("/payment/click", _click_handler)
    app.router.add_post("/payment/payme", _payme_handler)
    app.router.add_get("/health", _health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=PAYMENT_WEBHOOK_PORT)
    await site.start()
    logger.info("Payment webhook server слушает на 0.0.0.0:%s", PAYMENT_WEBHOOK_PORT)
    return runner
