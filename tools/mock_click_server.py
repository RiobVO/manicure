"""
Mock-сервер Click для локальной разработки (v.4 Phase 1).

Запуск:
    .venv/Scripts/python.exe tools/mock_click_server.py

В .env бота:
    PAYMENT_PROVIDER=click
    CLICK_SERVICE_ID=111
    CLICK_MERCHANT_ID=222
    CLICK_MERCHANT_USER_ID=333
    CLICK_SECRET_KEY=devsecret              # любое, главное чтобы совпадало
    CLICK_API_BASE=http://localhost:8444/mock-click/v2/merchant
    CLICK_PAY_URL_BASE=http://localhost:8444/mock-click/pay
    PAYMENT_PUBLIC_URL=http://localhost:8443
    PAYMENT_WEBHOOK_PORT=8443

Флоу (руками):
    1. В боте проходишь до confirm_yes.
    2. Бот зовёт /invoice/create — получает invoice_id.
    3. Бот присылает кнопку «Оплатить» на http://localhost:8444/mock-click/pay?...
    4. Жмёшь — mock считает правильную Click-подпись и шлёт prepare+complete
       в http://localhost:8443/payment/click.
    5. Бот помечает paid_at → присылает клиенту «✓ оплата получена»,
       админам — «💰 Оплата прошла».
"""
from __future__ import annotations

import hashlib
import os
import time
import uuid

import aiohttp
from aiohttp import web
from dotenv import load_dotenv

load_dotenv()

SECRET = os.getenv("CLICK_SECRET_KEY", "devsecret")
SERVICE_ID = os.getenv("CLICK_SERVICE_ID", "111")
BOT_PUBLIC = os.getenv("PAYMENT_PUBLIC_URL", "http://localhost:8443").rstrip("/")
BOT_WEBHOOK = f"{BOT_PUBLIC}/payment/click"
PORT = int(os.getenv("MOCK_CLICK_PORT", "8444"))


async def invoice_create(request: web.Request) -> web.Response:
    """POST /mock-click/v2/merchant/invoice/create — имитация Click API."""
    body = await request.json()
    invoice_id = str(uuid.uuid4().int)[:10]
    print(f"[mock-click] invoice/create appt={body.get('merchant_trans_id')} "
          f"amount={body.get('amount')} -> invoice_id={invoice_id}")
    return web.json_response({
        "error_code": 0,
        "error_note": "Success",
        "invoice_id": invoice_id,
    })


async def pay_page(request: web.Request) -> web.Response:
    """GET /mock-click/pay?... — HTML-страница с кнопкой «Оплатить»."""
    q = request.rel_url.query
    html = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><title>Mock Click Pay</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, sans-serif; padding: 40px; background:#f4f4f8; }}
  .card {{ background:#fff; padding:30px; border-radius:12px;
           max-width:420px; box-shadow:0 2px 12px rgba(0,0,0,.08); }}
  button {{ padding:14px 28px; background:#00a859; color:#fff;
            border:none; border-radius:8px; font-size:16px; cursor:pointer; }}
  button:hover {{ background:#008a47; }}
  dt {{ color:#888; font-size:11px; text-transform:uppercase; letter-spacing:.5px; }}
  dd {{ margin:0 0 12px 0; font-size:14px; }}
  h2 {{ margin-top:0; }}
</style></head><body>
<div class=card>
  <h2>Mock Click</h2>
  <dl>
    <dt>service_id</dt><dd>{q.get('service_id','')}</dd>
    <dt>merchant_id</dt><dd>{q.get('merchant_id','')}</dd>
    <dt>amount</dt><dd>{q.get('amount','')} UZS</dd>
    <dt>invoice_id</dt><dd>{q.get('transaction_param','')}</dd>
  </dl>
  <form method=post action=/mock-click/do-pay>
    <input type=hidden name=invoice_id value="{q.get('transaction_param','')}">
    <input type=hidden name=amount value="{q.get('amount','')}">
    <button type=submit>Оплатить</button>
  </form>
</div></body></html>"""
    return web.Response(text=html, content_type="text/html")


def _sign(click_trans_id: str, merchant_trans_id: str, merchant_prepare_id: str,
          amount: str, action: str, sign_time: str) -> str:
    raw = (
        f"{click_trans_id}{SERVICE_ID}{SECRET}{merchant_trans_id}"
        f"{merchant_prepare_id}{amount}{action}{sign_time}"
    )
    return hashlib.md5(raw.encode()).hexdigest()


async def do_pay(request: web.Request) -> web.Response:
    """
    POST /mock-click/do-pay — триггер эмуляции оплаты.
    Шлёт боту два webhook'а подряд: prepare (action=0) + complete (action=1).
    """
    form = await request.post()
    merchant_trans_id = str(form["invoice_id"])
    amount = str(form["amount"])
    click_trans_id = str(int(time.time()))
    sign_time = time.strftime("%Y-%m-%d %H:%M:%S")

    async with aiohttp.ClientSession() as session:
        # Prepare (action=0).
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
        print(f"[mock-click] -> prepare {BOT_WEBHOOK}")
        try:
            async with session.post(BOT_WEBHOOK, data=prep_data, timeout=aiohttp.ClientTimeout(total=5)) as r:
                prep_resp = await r.json()
                print(f"[mock-click]    bot resp (prepare): {prep_resp}")
        except Exception as exc:
            print(f"[mock-click] prepare ERROR: {exc}")
            return _pay_result_page(ok=False, reason=f"prepare failed: {exc}")

        merchant_prepare_id = str(prep_resp.get("merchant_prepare_id", ""))

        # Complete (action=1).
        sign_complete = _sign(
            click_trans_id, merchant_trans_id, merchant_prepare_id,
            amount, "1", sign_time,
        )
        comp_data = {
            **prep_data,
            "action": "1",
            "merchant_prepare_id": merchant_prepare_id,
            "sign_string": sign_complete,
        }
        print(f"[mock-click] -> complete {BOT_WEBHOOK}")
        try:
            async with session.post(BOT_WEBHOOK, data=comp_data, timeout=aiohttp.ClientTimeout(total=5)) as r:
                comp_resp = await r.json()
                print(f"[mock-click]    bot resp (complete): {comp_resp}")
        except Exception as exc:
            print(f"[mock-click] complete ERROR: {exc}")
            return _pay_result_page(ok=False, reason=f"complete failed: {exc}")

    return _pay_result_page(ok=True)


def _pay_result_page(ok: bool, reason: str = "") -> web.Response:
    if ok:
        html = "<h2>Оплачено (mock)</h2><p>Возвращайся в Telegram — бот уже в курсе.</p>"
    else:
        html = f"<h2>Ошибка</h2><p>{reason}</p>"
    return web.Response(text=html, content_type="text/html")


def main() -> None:
    app = web.Application()
    app.router.add_post("/mock-click/v2/merchant/invoice/create", invoice_create)
    app.router.add_get("/mock-click/pay", pay_page)
    app.router.add_post("/mock-click/do-pay", do_pay)
    print(f"[mock-click] listening on http://localhost:{PORT}")
    print(f"[mock-click] bot webhook -> {BOT_WEBHOOK}")
    print(f"[mock-click] shared secret: {SECRET!r}  service_id={SERVICE_ID}")
    web.run_app(app, host="0.0.0.0", port=PORT, print=None)


if __name__ == "__main__":
    main()
