# Онлайн-платежи (Click + Payme)

Phase 1 v.4. Поддерживает два узбекских провайдера. Выбирается через
`PAYMENT_PROVIDER={click|payme|none}` в `.env`.

---

## Общая схема

1. Клиент в боте доходит до подтверждения записи (`confirm_yes`).
2. Бот зовёт провайдера (`create_invoice`) и получает `invoice_id + pay_url`.
3. Клиент видит кнопку «💳 Оплатить» → тапает → открывается приложение
   Click / Payme → клиент платит.
4. Провайдер шлёт webhook на `https://<PAYMENT_PUBLIC_URL>/payment/{click|payme}`.
5. Бот проверяет подпись, помечает `appointments.paid_at = datetime('now')`,
   шлёт клиенту «✓ оплата получена» и админам «💰 Оплата прошла».

HTTP-сервер приёма webhook'ов поднимается **внутри bot-процесса** (aiohttp)
параллельно polling'у. Публичный HTTPS терминирует Caddy/nginx на хосте,
проксирует `/payment/*` и `/health` на `127.0.0.1:8443`.

---

## Переменные окружения

Смотри `.env.template` для полного списка. Минимальный набор на провайдера:

### Click

```bash
PAYMENT_PROVIDER=click
CLICK_SERVICE_ID=<число>        # "Service ID" в merchant.click.uz
CLICK_MERCHANT_ID=<число>       # "Merchant ID"
CLICK_MERCHANT_USER_ID=<число>  # "Merchant User ID" (для API-auth)
CLICK_SECRET_KEY=<строка>       # "Secret Key" (webhook signing)
PAYMENT_PUBLIC_URL=https://bot.<салон>.uz
PAYMENT_WEBHOOK_PORT=8443
```

### Payme

```bash
PAYMENT_PROVIDER=payme
PAYME_MERCHANT_ID=<строка>      # "Merchant ID" в merchant.paycom.uz
PAYME_SECRET_KEY=<строка>       # "KEY" из раздела "API" (TEST или PROD)
PAYMENT_PUBLIC_URL=https://bot.<салон>.uz
PAYMENT_WEBHOOK_PORT=8443
```

Fail-fast: если `PAYMENT_PROVIDER=click|payme`, но не заданы все креды —
бот не запустится. Явная ошибка в логах.

---

## Настройка Caddy (хост-сервис)

Нужно перед включением платежей. Caddy ставится отдельно от docker-compose,
автоматически тянет TLS через Let's Encrypt:

```caddy
bot.<салон>.uz {
    reverse_proxy /payment/* 127.0.0.1:8443
    reverse_proxy /health    127.0.0.1:8443
}
```

Проверка после деплоя:

```bash
curl -s https://bot.<салон>.uz/health
# ожидаем: ok
```

---

## Регистрация в кабинетах провайдеров

### Click (merchant.click.uz)

1. Заполнить заявление от юрлица/ЯТТ (см. бланк в чате с автором бота).
2. После одобрения Click → в кабинете «Услуги» → создать услугу.
3. Записать:
   - **Service ID** → `CLICK_SERVICE_ID`
   - **Merchant ID** → `CLICK_MERCHANT_ID`
   - **Merchant User ID** → `CLICK_MERCHANT_USER_ID`
   - **Secret Key** → `CLICK_SECRET_KEY`
4. В настройках услуги указать webhook-URL:
   - **Prepare + Complete** → `https://bot.<салон>.uz/payment/click`
   (один URL на оба шага — бот различает по полю `action`).

### Payme (merchant.paycom.uz)

1. Регистрация юрлица в Payme.
2. Создать кассу → во вкладке «API»:
   - **Merchant ID** → `PAYME_MERCHANT_ID`
   - **Secret Key (PROD)** → `PAYME_SECRET_KEY`
3. Webhook (endpoint приёма JSON-RPC от Payme):
   `https://bot.<салон>.uz/payment/payme`.

---

## Возврат денег при отмене оплаченной записи

Автоматический refund API НЕ реализован (deferred v4 Phase 5+).

Текущее поведение: при отмене записи, у которой `paid_at` не пуст, бот
отправляет в админ-чат алерт:

```
🔴 Нужен возврат
Запись #123 отменена после оплаты.
Клиент: Ирина
Сумма: 250 000 UZS
Провайдер: click
Инвойс: 9876543210

сделай возврат вручную в дашборде провайдера.
```

Админ делает refund через кабинет Click/Payme вручную. 4-5 кликов.
Для первых 20 салонов этого хватает.

---

## Локальная разработка (без реальных кабинетов)

Регистрация в Click занимает 5-10 дней, Payme — дольше. Для dev-теста
есть **mock-Click сервер**: `tools/mock_click_server.py`.

Запуск в двух терминалах:

```bash
# Терминал 1 — mock-провайдер
.venv/Scripts/python.exe tools/mock_click_server.py

# Терминал 2 — бот
.venv/Scripts/python.exe bot.py
```

В `.env`:

```bash
PAYMENT_PROVIDER=click
CLICK_SERVICE_ID=111
CLICK_MERCHANT_ID=222
CLICK_MERCHANT_USER_ID=333
CLICK_SECRET_KEY=devsecret
CLICK_API_BASE=http://localhost:8444/mock-click/v2/merchant
CLICK_PAY_URL_BASE=http://localhost:8444/mock-click/pay
PAYMENT_PUBLIC_URL=http://localhost:8443
PAYMENT_WEBHOOK_PORT=8443
```

Флоу:
1. В боте проходишь до `confirm_yes`.
2. Жмёшь «💳 Оплатить» → в браузере открывается mock-страница.
3. Жмёшь «Оплатить» → mock подписывает запрос тем же `devsecret`,
   что знает бот, и шлёт prepare+complete webhook'и.
4. Бот помечает paid → присылает «✓ оплата получена».

В проде `CLICK_API_BASE` и `CLICK_PAY_URL_BASE` оставить пустыми —
fallback на реальные `api.click.uz` и `my.click.uz`.

---

## Безопасность

- **Подпись Click.** `MD5(click_trans_id + service_id + SECRET_KEY +
  merchant_trans_id + [merchant_prepare_id] + amount + action + sign_time)`.
  Сравнение через `hmac.compare_digest` (constant-time, защита от тайминг-атак).
- **Подпись Payme.** JSON-RPC не подписан. Защита = `Authorization: Basic
  base64("Paycom:" + SECRET_KEY)`. Тоже `hmac.compare_digest`.
- **Fail-closed.** Любое непредусмотренное исключение в webhook → HTTP 401.
  Провайдеры корректно ретранут, и лучше ошибиться в пользу «не помечать
  paid», чем в пользу «принять всё подряд».
- **Idempotency.** `UNIQUE(payment_invoice_id)` partial index + проверка
  `paid_at IS NULL` в `mark_paid()`. Повторный webhook (retry от провайдера)
  не переписывает `paid_at` второй раз.
- **Rate-limit.** 60 req/min на IP для `/payment/click` и `/payment/payme`.
  Выше — что-то явно не так, 429.
- **Секреты.** `CLICK_SECRET_KEY` / `PAYME_SECRET_KEY` только в `.env`,
  никогда в логах, коде, git. При утечке — ротация в кабинете провайдера
  + редеплой.

### Тест подписи

Единственный обязательный тест (v4 Phase 1 spec):

```bash
.venv/Scripts/python.exe -m pytest tests/test_payment_webhook_forgery.py -v
```

Должно быть 3 PASSED. Если хоть один FAILED — релиз заблокирован,
фикс до мержа.

---

## Троблшут

**«Бот не принимает webhook, Click жалуется на 401»**
Проверить совпадение `CLICK_SECRET_KEY` в `.env` и в кабинете Click.
После изменения SECRET_KEY в кабинете — не забыть `docker compose up -d`.

**«Платёж прошёл у Click, но бот не помечает paid»**
Логи: `docker compose logs bot | grep -Ei "click|payme|payment"`.
Ищи `signature mismatch` / `invoice не найден`. Также проверить что
Caddy реально проксирует `/payment/click` (`curl /health` должен работать).

**«Клиент видит кнопку «Оплатить», но ссылка ведёт на ошибку Click»**
Неправильный `CLICK_SERVICE_ID` или `CLICK_MERCHANT_ID`. Это не про подпись
— это про параметры URL. Проверить в кабинете точные цифры.

**«Инвойс-ID повторяется → UNIQUE constraint violation»**
Это правильное поведение: дубль-webhook от провайдера. Лог покажет
`дубль webhook appt=X invoice=Y — игнор` — ничего делать не нужно.

---

## FUTURE

- Автоматический refund через API провайдеров (Click refund, Payme
  CancelTransaction) — при первой реальной жалобе клиента в проде.
- Полная поддержка Payme JSON-RPC методов (CheckPerform с реальной
  проверкой доступности, CancelTransaction-корректный).
- Частичные refund'ы, split-оплаты, промо-коды — вне Phase 1.
