# Architecture Decision Records

Формат: почему так, не что. Описание системы — в CLAUDE.md и коде.
Обновлять, когда принято новое архитектурное решение или сработал триггер пересмотра существующего.

---

## 1. SQLite + aiosqlite, не Postgres

**Контекст:** один салон = один инстанс бота = одна БД. Нагрузка: десятки записей в день, 2-5 мастеров, админ-панель + клиентский FSM. Всё локально на VPS.

**Решение:** SQLite в WAL-режиме, единый глобальный connection через `aiosqlite`, `BEGIN IMMEDIATE` + `asyncio.Lock` для сериализации writer'ов.

**Альтернативы:**
- Postgres — отброшен.
- MySQL — отброшен вместе с Postgres.

**Обоснование:**
- Ops-простота: один `.db` файл, бэкап = `cp`, restore = `cp` обратно. Клиент-салон не держит DBA.
- Установщик (`install.sh`) не ставит СУБД — только docker с ботом и Redis. Меньше ломающихся компонентов на fresh VPS.
- Изоляция тенантов: корруптировать БД соседа невозможно физически — её нет на этом VPS.
- Миграции через `PRAGMA user_version` без Alembic — 50 строк кода держат v0→v7.

**Что стоит:**
- Нет connection pool'а (единый connection). Один writer одновременно — защищено `asyncio.Lock`.
- Нет полноценных типов (DECIMAL, TIMESTAMP WITH TZ) — деньги храним в целых копейках, время как TEXT `YYYY-MM-DD HH:MM`.
- Нет replication для HA. Приемлемо: per-tenant бот, падение = один салон, не все.

**Триггер пересмотра:**
- Один тенант стабильно >20 мастеров одновременно → contention на write_lock.
- Booking latency p95 >500ms → читатель блокирует writer, пора за Postgres.
- SQLITE_BUSY в логах чаще раза в неделю на любом инстансе.

До этих триггеров Postgres = overhead без выигрыша.

---

## 2. Per-tenant VPS, не multi-tenant shared DB

**Контекст:** модель продаж — каждый салон покупает свой бот с brand'ом салона, своим токеном BotFather, своим `@bot_username`. Цель Year 1 — 80 салонов.

**Решение:** каждый салон получает отдельный VPS (или отдельный docker-compose stack), свой `.env`, свой BOT_TOKEN, свою SQLite БД. Общей инфраструктуры — ноль.

**Альтернативы:**
- Multi-tenant shared DB + tenant_id на каждой таблице — отброшен.
- Shared VPS с N-ю docker-compose стэками одного автора — потенциально, отложен.

**Обоснование:**
- Изоляция failure domain'а: падение одного салона ≠ падение всех. Баг в миграции → один outage, не 80.
- Простая биллинг-модель: перестал платить → `./scripts/uninstall.sh`. Не нужно удалять данные из shared БД с риском задеть соседа.
- Brand clarity: у каждого салона свой `@name_bot`, клиенту не показываешь «это часть сети». Некоторые салоны за это прямо платят больше.
- GDPR-like compliance проще: данные одного салона физически на его VPS, NDA ограничен.
- Отладка: `ssh vps && docker compose logs bot` — один процесс, один набор логов, нет cross-tenant шума.

**Что стоит:**
- Ручной rollout обновлений: N × SSH. Покрывается `./scripts/update.sh` + fleet-скрипт (когда станет больно).
- Нет cross-tenant аналитики из коробки (сколько записей у всех вместе). Покрывается через heartbeat в будущий fleet-dashboard (Phase 7).
- Стоимость VPS × N. На DigitalOcean $6/мес × 80 = $480/мес — мелочь в сравнении с подпиской клиента.

**Триггер пересмотра:**
- Вероятно — никогда. Per-tenant VPS — это **фича**, не tech-debt.
- Может пересмотреть если: средний ARPU падает ниже стоимости VPS × 3 (тогда дешёвые тенанты идут в shared).

---

## 3. aiogram 3, не aiogram 2.x / python-telegram-bot

**Контекст:** Python Telegram-бот с FSM (multi-step booking), inline-панелью, callback-flow, webhook-платежами.

**Решение:** aiogram 3.x (актуально 3.7+), FSM на Redis через `RedisStorage`, long-polling, Ed25519-лицензии, APScheduler в том же event loop.

**Альтернативы:**
- aiogram 2.x — отброшен, deprecated, нет bugfix'ов.
- python-telegram-bot — отброшен.

**Обоснование:**
- Native async/await: event loop для бота + APScheduler + webhook aiohttp-сервера в одном процессе, без потоков.
- Явный Router-based routing с F-фильтрами: `F.data.startswith("appt_")` читабельнее декораторов в 2.x.
- Pydantic-типы на Message/CallbackQuery: меньше KeyError на живых данных.
- Middleware-система: `TimingMiddleware`, `LicenseGateMiddleware` встают в конвейер без monkey-patch'а.
- Активно поддерживается, фиксы TG API прилетают быстро.

**Что стоит:**
- Breaking changes между минорами (3.6→3.7 меняли storage API). Pin в `requirements.txt` обязателен.
- Мало готовых примеров для редких кейсов (payment webhooks вне Telegram Bot Payments API) — пишем руками.
- Error-handler требует `return True` для подавления, иначе polling панически перезапускается.

**Триггер пересмотра:**
- aiogram 4 стабилизируется и 3.x идёт в security-only режим → миграция.
- Telegram вводит что-то, что aiogram не поддерживает >6 месяцев, а PTB поддерживает.

До этого — 3.x держим.

---

## Шаблон новой ADR

```
## N. <Решение одной фразой>
Контекст: ...
Решение: ...
Альтернативы: ...
Обоснование: ...
Что стоит: ...
Триггер пересмотра: ...
```

Не описываем КАК работает (это в коде и CLAUDE.md). Только ПОЧЕМУ выбрано и когда переразмышлять.
