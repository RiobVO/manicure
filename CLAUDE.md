# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Bot

**Продакшн (docker):**
```bash
./install.sh <tenant_slug> <admin_id>               # первый деплой на VPS (BOT_TOKEN — интерактивно или env)
docker compose up -d --build                        # пересборка после правок python-кода
./scripts/update.sh                                 # git pull + rebuild
./scripts/uninstall.sh                              # архив в /root + снос
./scripts/restore.sh <backup.db>                    # восстановление БД из бэкапа (см. docs/RESTORE.md)
./scripts/reset_demo.sh                             # сброс демо-инстанса
```

**Локальная разработка:**
```bash
pip install -r requirements.txt
python bot.py
```

**Тесты:**
```bash
pip install -r requirements-dev.txt                 # pytest + pytest-asyncio (один раз)
pytest                                              # 110 интеграционных, asyncio_mode=auto
pytest tests/test_appointments.py                   # один файл
pytest tests/test_appointments.py::test_create      # один тест
pytest -k "reminder"                                # по подстроке
```

CI: `.github/workflows/tests.yml` гоняет `pytest` на push/PR в main (Python 3.12, ubuntu-latest, кэш pip).

**Локальный мок Click для тестирования платежей без мерчант-аккаунта:**
```bash
python tools/mock_click_server.py                   # отдельный процесс, см. .env CLICK_API_BASE
```

### .env

Обязательные переменные:
```
BOT_TOKEN=<токен от @BotFather>
ADMIN_IDS=123456789,987654321      # Telegram user_id через запятую
TENANT_SLUG=salon-slug             # [a-z0-9-]
REDIS_URL=redis://localhost:6379/0 # в docker: redis://redis:6379/0
TIMEZONE=Asia/Tashkent             # IANA, default Asia/Tashkent
```

Опциональные:
```
BACKUP_CHAT_ID=-100...       # приватный канал для бэкапов БД (каждые 6ч)
ERROR_CHAT_ID=-100...        # канал для алертов об unhandled exceptions + license-expiry
LICENSE_KEY=<blob>           # Ed25519-подписанный ключ от tools/issue_license.py
HEARTBEAT_URL=https://...    # эндпоинт для daily heartbeat-POST (https-only, кроме localhost)
LICENSE_CONTACT=@handle      # для сообщения "лицензия истекла, обратитесь к X"
DB_PATH=manicure.db          # путь к SQLite-файлу
```

Платежи (см. секцию **Payments** ниже, по умолчанию выключены):
```
PAYMENT_PROVIDER=none                    # click | payme | none
PAYMENT_URL=...                          # legacy deeplink-кнопка (только при provider=none)
PAYMENT_LABEL=Оплатить                   # текст кнопки legacy
CLICK_SERVICE_ID, CLICK_MERCHANT_ID, CLICK_MERCHANT_USER_ID, CLICK_SECRET_KEY
CLICK_API_BASE, CLICK_PAY_URL_BASE       # для мока в dev
PAYME_MERCHANT_ID, PAYME_SECRET_KEY
PAYMENT_PUBLIC_URL=https://...           # куда Caddy/nginx проксирует webhook (https only)
PAYMENT_WEBHOOK_PORT=8443                # локальный порт aiohttp за reverse-proxy
```

Telegram webhook вместо polling (опционально, см. `### Webhook режим` ниже):
```
WEBHOOK_URL=https://salon.example/tg/webhook   # пусто → polling
WEBHOOK_PORT=8081                              # внутренний aiohttp port за reverse-proxy
WEBHOOK_SECRET=<random-token>                  # рекомендуется: secret_token validation
WEBHOOK_PATH=/tg/webhook                       # internal path, должен совпадать с хвостом WEBHOOK_URL
```

`config.py` фейлит запуск (fail-fast), если:
- HTTPS-валидация любого URL (кроме localhost-моков),
- `PAYMENT_PROVIDER != "none"` без полного набора credentials,
- `TIMEZONE` отсутствует в IANA.

## Architecture Overview

Telegram-бот записи на маникюр на **aiogram 3.7**, SQLite через **aiosqlite**, напоминания через **APScheduler**, FSM-storage в **Redis** (fallback на MemoryStorage). Один процесс python — он принимает Telegram-апдейты (polling **или** webhook, см. `WEBHOOK_URL`), поднимает aiohttp webhook-server для платежей, гоняет scheduler. Без отдельных контейнеров.

Зависимости (`requirements.txt`): `aiogram==3.7.0`, `aiosqlite==0.20.0`, `apscheduler==3.10.4`, `python-dotenv==1.0.1`, `openpyxl==3.1.5` (Excel-экспорт), `redis==5.2.1`, `cryptography==43.0.3` (Ed25519-лицензии), `qrcode[pil]==7.4.2` (QR-плакаты). Dev-only: `requirements-dev.txt` — `pytest>=8.0`, `pytest-asyncio>=0.23`.

### Три режима пользователя

- **Клиент** — бронирует через FSM `BookingStates`: **категория (6 групп: руки/ноги/лицо/воск/шугаринг/уход) → услуга с ценой → аддоны → мастер → дата → время → подтверждение профиля → имя → телефон → подтверждение.** Если `settings.use_categories="0"` — шаг `choose_category` пропускается, клиент видит плоский список всех активных услуг (для салонов одного профиля). После confirm transient-сообщения (вопросы имени/телефона/summary) удаляются, остаются только hero + blockquote + напоминалка. Клиентские UI-сообщения двуязычные (RU/UZ, см. `utils/i18n.py`).
- **Админ** — управляет записями, услугами, расписанием, мастерами, блокировками, статистикой, источниками трафика через единую inline-панель + команды `/status`, `/language`. Админ-интерфейс **только на русском**.
- **Мастер** — `handlers/master.py` (FSM `MasterStates`). Self-serve кабинет: видит свои записи на сегодня и ближайшие, может перенести/отменить **свою** запись. Активируется когда `masters.user_id` совпадает с `from_user.id` (фильтр `IsMasterFilter`). Мастер не может быть админом одновременно — если оба совпадают, проверяется в порядке регистрации роутеров.

Определение роли: `utils/admin.py:is_admin()` проверяет `ADMIN_IDS` из `.env` **и** `_db_admins_cache` (runtime-кэш из таблицы `admins`). Кэш загружается при старте через `refresh_admins_cache()` и обновляется при добавлении/удалении через `handlers/admin_manage.py`. Мастера кешируются через `refresh_masters_cache()`.

### Порядок регистрации роутеров (критически важно)

`bot.py::main` строго:

1. **Middlewares** на `dp.message` и `dp.callback_query` (порядок имеет значение):
   - `TimingMiddleware` — первым, чтобы покрыть всё, включая license_gate.
   - `AntiSpamCallbackMiddleware` — **только на `dp.callback_query`** (на `dp.message` не вешается). Между timing и license_gate.
   - `LicenseGateMiddleware` — последним, до хендлеров.
2. **Admin-роутеры** все вместе: `admin`, `admin_appointments`, `admin_clients`, `admin_services`, `admin_stats`, `admin_status`, `admin_settings`, `admin_blocks`, `admin_manage`, `admin_masters`, `admin_master_schedule`, `admin_export`, `admin_traffic`, **`admin_quick_add`** (последним из админских — у него свой неймспейс `qadd_*`, регистрируется после `admin_appointments` потому что у того общий day-view хендлер).
3. **`@dp.errors()`** — глобальный ловец unhandled exceptions, шлёт в `ERROR_CHAT_ID` через `report_error()`, пользователю короткий ack чтобы не висели часики. Возвращает `True` всегда — иначе aiogram паникует в polling loop.
4. **`master.router`** — после всех admin (фильтр `IsMasterFilter` ловит только активных мастеров с `user_id`), но **до** клиентских роутеров.
5. **`reviews.router`** — до `client.router`, иначе catch-all поглотит `rev_*` callback'и.
6. **`client_reminders`, `client_history`, `client.router`** — `client` строго последним: содержит catch-all `fallback_message`, который перехватил бы текстовые сообщения FSM-потоков других ролей.

После роутеров: `init_db()` → `refresh_admins_cache()` → `refresh_masters_cache()` → старт scheduler → старт payment webhook server (если `PAYMENT_PROVIDER != "none"`) → `mark_started()` (для `/status`) → `dp.start_polling()` **или** `_start_webhook()` (если задан `WEBHOOK_URL`).

### Middlewares

- **`middlewares/timing.py::TimingMiddleware`** — каждый хендлер пишет `timing: msg user=X text='/start' duration=231ms`. WARNING при `duration > 500ms`, ERROR при `> 1500ms`. Быстрые — в DEBUG чтобы не захламлять INFO.
- **`middlewares/anti_spam.py::AntiSpamCallbackMiddleware`** — два слоя защиты от Telegram rate-limit на callback'ах:
  - Слой 1: `MIN_INTERVAL_MS = 1500` мс между **одинаковыми** callback'ами от одного user'а — нервный двойной/тройной тап на ту же кнопку.
  - Слой 2: `MIN_USER_INTERVAL_MS = 400` мс между **любыми** callback'ами от одного user'а — TG лимит «1 edit_message/сек на чат» при быстрой навигации (категория → услуга → мастер → дата → время за 3-5с давал 429 + 3-секундное «залипание»).
  - Дроп = пустой `event.answer()` (спиннер исчезает) + `return None` (хендлер не вызывается). GC раз в 1000 событий чистит протухшие записи.
- **`middlewares/license_gate.py::LicenseGateMiddleware`** — блокирует все хендлеры в `LicenseMode.RESTRICTED`. Пропускает только `/start` с фиксированным сообщением; на callback'и отвечает `show_alert`. В режимах `OK`, `GRACE`, `DEV` пропускает всё.

### Webhook режим

`WEBHOOK_URL` пуст → polling (как раньше). Задан → `bot.py::_start_webhook` поднимает aiohttp на `WEBHOOK_PORT` (default 8081), регистрирует `set_webhook(url=WEBHOOK_URL, secret_token=WEBHOOK_SECRET, drop_pending_updates=True, allowed_updates=dp.resolve_used_update_types())`. Caddy/nginx должен проксировать `WEBHOOK_PATH` (default `/tg/webhook`) на этот порт.

Зачем: убирает 100-500мс polling round-trip на каждом callback. `WEBHOOK_SECRET` — рекомендован: aiogram сам отбросит запросы без `X-Telegram-Bot-Api-Secret-Token`. На shutdown — `delete_webhook()` + `runner.cleanup()`.

`drop_pending_updates=True` — при переходе с polling в очереди могут лежать необработанные клики; без drop они выстрелят дважды.

### База данных

Единый глобальный connection (`db/connection.py::_db`), открывается лениво в `get_db()`, инициализируется через `init_db()`, закрывается в `close_db()`. WAL-режим и `PRAGMA foreign_keys=ON` включены сразу после connect.

**Не использовать `aiosqlite.connect()` напрямую** в новых функциях — только `get_db()`. Иначе теряется WAL-режим и появляются race-condition окна.

**Write-lock:** глобальный `asyncio.Lock` через `get_write_lock()` сериализует write-транзакции (`BEGIN IMMEDIATE`). Создаётся **в `init_db()`**, не лениво (ленивое создание было TOCTOU — две корутины могли получить разные локи). Все DB-функции с записью обязаны брать этот lock + `BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK`.

**`row_factory` глобального connection НИКОГДА не меняется** — используется `_dict_rows()` / `_dict_row()` через локальный cursor с `aiosqlite.Row`.

#### Таблицы

`appointments` (id, user_id, name, phone, service_id, service_name, service_duration, date, time, confirmed, created_at, status, service_price, client_cancelled, **cancel_reason**, **master_id**, **paid_at**, **payment_provider**, **payment_invoice_id**, **payment_pay_url**, **payment_message_id**) — жирная таблица, центральная.

`services` (id, name, price, duration, is_active, sort_order, description, photo_file_id, **category** ∈ `hands|feet|face|wax|sugar|care`) + `UNIQUE INDEX idx_services_name_category(name, category)` (с миграции v9→v10 — защита от дублей при повторных seed). Поле `category` — TEXT без CHECK-констрейнта (лояльно к будущим расширениям), но на UI/handler уровне ограничено `constants.CATEGORY_KEYS`.

`service_addons` (id, service_id, name, price, is_active, sort_order) — доп. опции.

`appointment_addons` (appointment_id, addon_id, price) — выбранные аддоны на запись.

`masters` (id, user_id UNIQUE, name, photo_file_id, bio, is_active, sort_order).

`master_schedule` (master_id, weekday, work_start, work_end) — per-master недельный график.

`weekly_schedule` (weekday, work_start, work_end) — салонно-глобальный fallback.

`blocked_slots` (id, date, time_start, time_end, is_day_off, reason, **master_id**) — блокировки.

`client_profiles` (user_id, name, phone, **source**, **lang 'ru'|'uz' default 'ru'**) — `source` фиксируется при ПЕРВОМ `/start <code>` и больше не переписывается.

`sent_reminders` (id, appointment_id, reminder_type, sent_at, UNIQUE(appointment_id, reminder_type)) — дедуп.

`admin_logs` (id, admin_id, action, target_type, target_id, details, created_at) — audit, ретеншн 180 дней.

`admins` (user_id, added_by, added_at, comment) — DB-добавленные админы поверх `.env`.

`reviews` (см. `db/connection.py`) — оценки + комментарии.

`traffic_sources` (id, code UNIQUE, label, created_at) — источники атрибуции; на старте seed `desk`/`mirror`/`door`.

`settings` (key, value) — k/v: `slot_step`, `salon_contact` (для сообщений об отмене), `salon_name` (для QR-плакатов), `use_categories` (`"0"|"1"` — двухуровневое меню vs плоский список услуг), `cat_a_label`..`cat_f_label` (подписи 6 категорий, редактируются админом без перезапуска; параллельно `constants.CATEGORY_KEYS = (hands, feet, face, wax, sugar, care)` и `CATEGORY_ALPHA = (А, Б, В, Г, Д, Е)` для админ-UI).

#### Миграции

Через `PRAGMA user_version` в `db/connection.py::init_db`. Текущая версия — **10**. Миграции идемпотентны (try/except `duplicate column`).

| Версия | Что добавлено |
|---|---|
| v0→v1 | `appointments.cancel_reason`, `appointments.master_id`, `blocked_slots.master_id` |
| v1→v2 | `services.category` (`'hands'\|'feet'`), бэкфилл по имени (`педикюр*` → feet, остальное → hands) |
| v2→v3 | `appointments.{paid_at, payment_provider, payment_invoice_id}` + partial UNIQUE-индекс `idx_appt_invoice_unique WHERE payment_invoice_id IS NOT NULL` (идемпотентность webhook) |
| v3→v4 | `appointments.payment_pay_url` (чтобы не звать `create_invoice` повторно при возврате клиента) |
| v4→v5 | `traffic_sources` + `client_profiles.source` + seed `desk`/`mirror`/`door` |
| v5→v6 | `client_profiles.lang` (RU/UZ) |
| v6→v7 | `appointments.payment_message_id` — id pay-сообщения, удаляется после успешной оплаты (Click повторно бы списал) |
| v7→v8 | расширение каталога с 2 до 6 категорий — `INSERT OR IGNORE` дефолтных `cat_a..cat_f_label` в `settings`. ALTER не нужен: `services.category` без CHECK-констрейнта, любые значения принимаются. |
| v8→v9 | реструктуризация категорий: `depil` распадается на `wax` (с обрезкой префикса «Воск — » в `name`) и `sugar` («Шугаринг — »); `skincare`+`dental` → `care`. «Воск — подмышки» удаляется если без записей. Хвостовые `depil` без префикса метода логируются WARN — переносятся админом вручную через `svc_setcat`. |
| v9→v10 | дедуп `services` по `(name, category)`: для каждой группы с >1 строкой остаётся минимальный `id`, `appointments.service_id` и `service_addons.service_id` переезжают на него, дубли удаляются (CASCADE на `appointment_addons`); создаётся `UNIQUE INDEX idx_services_name_category(name, category)` — защита от повторного появления дублей. |

`db/seed.py::SERVICES` — только при пустой таблице `services`.

**Дефолтный мастер:** если таблица `masters` пуста после миграций — создаётся master `'Мастер'` и `weekly_schedule` копируется в `master_schedule` для него.

**FSM-хранилище (Redis):** `bot.py::_build_storage`. Если `REDIS_URL` пуст или Redis недоступен (ping с таймаутом 3с) — fallback на `MemoryStorage` с WARN. TTL = 24ч на state и data (брошенные booking-флоу не копятся вечно). Любая ошибка Redis → не падаем.

### FSM States (`states.py`)

- **`BookingStates`**: `choose_category` → `choose_service` → `choose_addons` → `choose_master` → `choose_date` → `choose_time` → `confirm_profile` → `get_name` → `get_phone` → `confirm`. При `use_categories="0"` экран `choose_category` пропускается — клиент сразу видит список всех активных услуг.
- **`ReviewStates`**: `enter_comment` (после выбора рейтинга 1-5).
- **`AdminStates`**: редактирование/добавление услуг (с шагом `service_add_category`), перенос записей, настройки (`slot_step`/`contact`/`salon_name`/`cat_a..cat_f_label` × 6 — `settings_edit_cat_<a..f>_label`), графики (салонный + per-master), блокировки, аддоны, мастера, источники трафика (`traffic_source_add_code`/`add_label`), `client_search`.
- **`AdminQuickAddStates`** (`handlers/admin_quick_add.py`): `enter_name` → `enter_phone` (опционально) → `pick_service` → `pick_master` → `pick_time` → `confirm`. Сценарий — владелец на стойке записывает звонящего клиента из дневного вида админ-панели за 5 шагов. Все callback'и в неймспейсе `qadd_*`. Запись создаётся через `create_appointment` (write-lock + проверка пересечений), `user_id = id админа` для NOT NULL.
- **`MasterStates`**: `reschedule_pick_date` → `reschedule_pick_time` (мастер переносит свою запись).

### Планировщик (`scheduler.py`)

`AsyncIOScheduler` с TZ из `config.TZ`. Все задачи обёрнуты в `_safe_*` — unhandled exceptions уходят в `report_error`, джоба не падает молча.

| Задача | Триггер | Что делает |
|---|---|---|
| `_safe_send_reminders` | каждые 15 мин (`REMINDER_POLL_INTERVAL_MIN`) | `reminder_24h` (окно 20-28ч), `reminder_2h` (окно 1.5-2.5ч). Дедуп через `sent_reminders`. Текст напоминаний на языке клиента (`get_user_lang`). `TelegramForbiddenError` (клиент заблокировал бота) → пишем в `sent_reminders` чтобы выйти из цикла. Прошедшее окно (бот был оффлайн) → маркируем как «отправлено» с WARN. |
| `_touch_heartbeat` | каждые 5 мин, сразу при старте | `<DB_PATH>/.heartbeat` mtime. Используется docker `HEALTHCHECK` (окно 30 мин = 6× запас). Не mtime БД, потому что в WAL `SELECT` не трогает main-файл и в простой день mtime протухает. |
| `_safe_run_backup` | каждые 6ч | `_prune_old_rows` (admin_logs >180 дн., sent_reminders >90 дн., атомарно под write_lock + BEGIN IMMEDIATE) → `backup_db()` (локальная копия в `./backups/`, ротация 7) → отправка в `BACKUP_CHAT_ID` если задан (`[<slug>] backup <ts> · <size>MB`). RPO=6ч. |
| `send_heartbeat` | каждые 24ч, сразу при старте | POST `{tenant_slug, license_id, license_expires_at, version, last_seen}` на `HEARTBEAT_URL`. `license_id` может быть `None` (DEV/RESTRICTED) — отправляем как есть. Ошибка не блокирует бот. |
| `_safe_alert_license_expiry` | каждые 24ч, сразу при старте | За ≤60 дн. до истечения (но >0) шлёт пуш в `ERROR_CHAT_ID`. Дедуп 7 дней через файл-маркер `<DB_PATH>/.license_alert`. |

### Платежи (Phase 1 v.4)

Click/Payme полностью реализованы, но **по умолчанию выключены** через `PAYMENT_PROVIDER=none` (см. `FUTURE.md` — Сабина принимает наличными).

- **`utils/payments/base.py`** — абстракция `PaymentProvider` (`create_invoice`, `verify_and_parse`).
- **`utils/payments/click.py`**, **`utils/payments/payme.py`** — конкретные провайдеры.
- **`utils/payments/server.py`** — aiohttp webhook-server, стартует **в том же процессе** что polling (отдельный task), порт `PAYMENT_WEBHOOK_PORT` (default 8443) за reverse-proxy на `PAYMENT_PUBLIC_URL`.
  - Подпись/Basic auth проверяется **до** обработки тела (в `verify_and_parse`).
  - Rate-limit: 60 req/min на IP (in-memory sliding window).
  - **Fail-closed**: любое непредусмотренное исключение → 401 (провайдер ретранет, лучше молчать чем marked-paid по багу).
- **`db/payments.py::mark_paid`** — идемпотентен на уровне БД (не переписывает `paid_at`).
- **Pay-сообщение в чате клиента:** url-кнопка нельзя «убить» постфактум, поэтому после успешной оплаты бот удаляет всё сообщение через `bot.delete_message` (по `payment_message_id`). Иначе клиент тапнет повторно и Click спишет ещё раз (Payme защищён на `CheckPerformTransaction`).
- **Mock-сервер для dev:** `tools/mock_click_server.py` + `.env` `CLICK_API_BASE=http://localhost:8444/mock-click/v2/merchant`.

Активация в проде: триггеры и step-by-step — в `FUTURE.md` (получить мерчант → `.env` → `PAYMENT_PROVIDER=click|payme` → Caddy/nginx → callback URL в кабинете → тест на 1000 UZS → убрать warning-suppression).

Тесты: `tests/test_payment_cancelled_after_pay.py`, `tests/test_payment_webhook_forgery.py`.

### Атрибуция трафика (Phase 2 v.4)

- **`utils/qrgen.py::generate_qr`** — A5-плакат (читается с ~1 м), `error_correction=H`, шрифт DejaVuSans-Bold (поставляется через Dockerfile пакетом `fonts-dejavu-core`). Возвращает PNG-bytes через `BytesIO` без записи на диск. Layout: `salon_name` (мелко) → `source_label` (крупно) → QR → `bottom_caption` (по умолчанию «отсканируй — запишись»).
- **`db/traffic.py`** — CRUD `traffic_sources` + `list_sources_with_stats`.
- **`handlers/admin_traffic.py`** — экран «📍 Источники»: список, статистика, добавить, удалить, выгрузить QR-плакат.
- **`handlers/client.py::cmd_start`** ловит `/start <code>`, ищет `traffic_sources.code`, фиксирует в `client_profiles.source` **только при первом `/start`** (последующие переходы не переписывают, иначе сломалась бы статистика).

Дефолтные источники (seed на v4→v5): `desk` (Ресепшн), `mirror` (Зеркало), `door` (Дверь). Спека ограничивает 50 источников на салон.

Название салона для подписи плаката хранится в `settings['salon_name']` (редактируется в админке).

### i18n RU + UZ (Phase 3 v.4)

- **`utils/i18n.py`** — таблица `{key: {ru, uz}}`. Класс `Lang` (`RU`/`UZ`/`DEFAULT`/`normalize`). Функция `t(key, lang, **fmt)` с fallback на `ru` + WARN если ключа нет на нужном языке.
- **`db/clients.py::get_user_lang` / `set_user_lang`** — читает/пишет `client_profiles.lang`.
- **Admin-панель остаётся на русском.** Узбекский — только клиентские сообщения и кнопки.
- **Команда `/language`** — переключатель. Регистрируется в Telegram-меню через `bot.set_my_commands` для дефолтного и `language_code='uz'` (синяя «/»-кнопка показывает локальную подпись).
- Существующие клиенты до миграции v5→v6 — `lang='ru'` по дефолту, не спрашиваем заново. Новые — выбирают на первом `/start`.
- Напоминания (`scheduler.py`) шлются на языке клиента.

### Error reporting

- **`utils/error_reporter.py::report_error`** + **`@dp.errors()`** в `bot.py` — unhandled exceptions из хендлеров и scheduler-задач уходят в `ERROR_CHAT_ID` с тегом `[TENANT_SLUG]`, контекстом и traceback'ом. Внутри хранит `_last_error` и `_start_time` (через `mark_started()` в `bot.py::main`) для команды `/status`.
- **`handlers/admin_status.py`** — `/status` показывает uptime, последнюю ошибку, состояние лицензии, счётчики записей.

### Licensing

- **`utils/license.py`** — Ed25519-подписанные ключи. Публичный ключ вмёрзнут в `PUBLIC_KEY_PEM` (запущенный бот не читает файлов). Приватный ключ — у автора в `license_private_key.pem` (gitignored).
- **Режимы (`LicenseMode`):** `DEV` (placeholder в `PUBLIC_KEY_PEM` — пропускает всё), `OK`, `GRACE` (истекла ≤ `GRACE_DAYS=90` назад), `RESTRICTED` (нет/невалид/истекла >90 дн.).
- **`middlewares/license_gate.py`** — **enforcement on**, gate зарегистрирован в `bot.py` сразу после `TimingMiddleware`. В `RESTRICTED` бот отвечает только на `/start` с текстом про лицензию и `LICENSE_CONTACT`. На callback'и — `show_alert` «Лицензия бота истекла».
- **На старте в `GRACE`** — `_warn_grace` рассылает админам «лицензия истекла, до блокировки N дн.».
- **Проактивный алерт** автору за ≤60 дн. до истечения — в `ERROR_CHAT_ID`, дедуп 7 дн. через файл `<DB_PATH>/.license_alert`. Команда продления печатается прямо в алерте.
- Инструменты автора: `tools/generate_keys.py` (разово), `tools/issue_license.py` (на каждую продажу). Полный флоу — `docs/LICENSING.md`.

### Панель администратора

`utils/panel.py` — трекер «живого» сообщения-панели (один `message_id` на чат). `edit_panel()` редактирует это сообщение; при `TelegramBadRequest` — удаляет и создаёт заново. `asyncio.Lock` на каждый чат предотвращает дубли при быстрых кликах. Для админских чатов запоминается reply-клавиатура через `set_reply_kb`.

### Клавиатуры (`keyboards/inline.py`)

Callback-data форматы (по группам):

- **Клиент:** `cat_<a..f>|cat_back` (6 категорий, см. `constants.CATEGORY_KEYS`), `service_<id>`, `addon_<id>`, `addons_done`, `master_<id>`, `date_<YYYY-MM-DD>`, `time_<HH:MM>`, `confirm_yes|confirm_no`, `cr_<key>_<appt_id>` (cancel reason), `my_appt_<id>`, `client_my_appointments`, `history_page_<n>`.
- **Админ — записи:** `appt_detail_<id>`, `appt_status_<id>_<status>`, `appt_cancel_<id>`, `admin_today|admin_tomorrow|admin_cal|admin_home`, `cal_day_<year>_<month>_<day>`, `cal_noop`. Календарь админа подсвечивает дни с записями/блокировками визуальными отметками.
- **Админ — услуги:** `svc_*`, `svc_cat_<hands|feet|face|wax|sugar|care>`, `svc_setcat_<id>_<cat>`, `svc_detail_<id>`, `svc_addons_<id>`, `addon_detail_<id>`, `addon_toggle_<id>`, `addon_delete_<id>`, `addon_add_<service_id>`. Список услуг группируется по категориям и пагинируется. Активные услуги с `price=0` подсвечиваются ⚠️. Кнопка услуги показывает счётчик активных аддонов.
- **Админ — мастера:** `master_card_<id>`, `master_add`, `master_edit_{name|uid|bio}_<id>`, `master_sched_<id>`, `master_toggle_<id>`, `master_delete_<id>`.
- **Админ — блокировки:** `block_master_all`, `block_master_<id>`, `block_*`. Из календаря — блок дня одним тапом.
- **Админ — настройки:** `settings_*` (включая `settings_use_categories_<0|1>`, `settings_edit_cat_<a..f>_label`).
- **Админ — quick-add:** `qadd_*` (отдельный неймспейс для FSM `AdminQuickAddStates`).
- **Отзывы:** `rev_rate_<appt>_<1..5>`, `rev_*`.

Кнопки услуг содержат цену: `гель-лак · 150 000`. Префикс «маникюр/педикюр» в новых категориях не используется (метод понятен из категории — например `wax` это «воск», у услуги внутри категории просто `руки полностью`). Цены без «сум», пробел-разделитель тысяч (`_price_short` в `inline.py`).

Парсинг callback'ов через `utils/callbacks.py::parse_callback` (whitelist префиксов, разделитель `_`). Хрупкое место: коды трафика типа `story_apr20` уже содержат `_`, см. FUTURE.md про переход на `:`-разделитель.

### Настройки графика и слотов

- Часы работы хранятся в **`master_schedule`** (per-master) и **`weekly_schedule`** (салонно-глобальный fallback). Не в `settings`.
- `settings.slot_step` (минут) — шаг слотов в букинге. Допустимые значения — `VALID_SLOT_STEPS = {15, 20, 30, 60}` (`constants.py`).
- `settings.salon_contact` — показывается клиентам в сообщениях об отмене оплаченных записей.
- `settings.salon_name` — подзаголовок над `source_label` на QR-плакатах. Пусто → не рисуется.
- `settings.use_categories` (`"0"|"1"`) — двухуровневое меню (категория → услуга) или плоский список всех активных услуг.
- `settings.cat_<a..f>_label` — подписи 6 категорий (с эмодзи). Дефолты в `constants.CATEGORY_DEFAULT_LABELS`. Применяются миграцией v7→v8 через `INSERT OR IGNORE` (если админ уже переименовал — не перезаписываются).
- `MIN_BOOKING_ADVANCE_HOURS = 3`, `BOOKING_DAYS_AVAILABLE = 14` — `constants.py`.

### Утилиты (`utils/`)

- `utils/admin.py` — `is_admin()`, `IsAdminFilter`, `is_admin_callback`, `is_admin_message`, `deny_access`, `all_admin_ids`, `refresh_admins_cache`/`refresh_masters_cache`. Кэши в памяти процесса.
- `utils/notifications.py` — шаблоны сообщений мастеру/клиенту, `notify_master`, `broadcast_to_admins` (через `asyncio.gather` с `return_exceptions=True` — один упавший send_message не валит остальных). Latency confirmation 4-5с → ~1с после переноса в `asyncio.create_task`.
- `utils/callbacks.py::parse_callback` — разбор callback-data по префиксу.
- `utils/timezone.py::now_local()` — единый источник времени в TZ из `config.TZ`. Раньше жил в `constants.py`, перенесён.
- `utils/panel.py` — «живая» панель админа (`edit_panel`, `set_reply_kb`, `_panel_msg_ids`).
- `utils/payment_ui.py` — рендер pay-кнопок и сообщений.
- `utils/salon_info.py` — `salon_name`/`salon_contact` getters.
- `utils/ui.py` — общие хелперы рендера (даты, цены, blockquote-форматирование).
- `utils/validators.py` — валидация ввода (имя, телефон).
- `utils/i18n.py` — таблица RU/UZ + `t(key, lang, **fmt)`.
- `utils/qrgen.py` — A5-плакаты с QR.
- `utils/error_reporter.py` — `report_error`, `mark_started`, `_last_error`.
- `utils/license.py` — Ed25519, `evaluate_license`, `LicenseMode`.
- `utils/heartbeat.py` — daily POST на `HEARTBEAT_URL`.
- `utils/payments/{base,click,payme,server}.py` — Phase 1 v.4.

## Dev Preferences

- **Тесты**: не писать, если пользователь явно не попросил. **110 интеграционных** в `tests/` (`asyncio_mode=auto`, `addopts=-v --tb=short`) — не ломать.
- **Коммиты**: не оставлять локально. После коммита — сразу `git push origin main`. Не копить висящие коммиты на локале. Исключение — если автор явно сказал «не пушь».
- **Верификация провалилась**: использовать `debug-context` скилл, диагностировать причину, предложить fix — не ждать решения пользователя.
- **Пересборка после правок**: автор работает в docker. После изменения python-кода — `docker compose up -d --build`. После изменения только `.env` — обычно `docker compose up -d` достаточно, но с `--build` надёжнее.
- **Автор тестирует руками**. Не запускай `python bot.py` сам, не шли запросы в прод-бот. Только даёшь команды, он их выполняет.
- **Recap в конце сессии**. Когда задача или серия связанных работ закрыта (закоммичено, запушено, верификация прошла), написать итоговую строку в формате:
  `※ recap: <через + перечень доставленного>. Следующий шаг: <что дальше>. (disable recaps in /config)`
  Триггер — логическое завершение темы: ответ на «что дальше?», закрытие инцидента, push финального коммита. Не писать recap после каждого ответа — только в конце сессии/блока.

---

## Commercial Readiness Track

Продукт готовится к продаже реальным бьюти-салонам в Узбекистане. Каждый салон — свой VPS, свой bot token, своя БД (**не** multi-tenant — изоляция намеренно выбрана над элегантностью). Автор сам продаёт, ставит и саппортит. Цель Year 1 — 80 салонов, не 400.

**Детали 7 фаз, verification-команды, don'ts — в `docs/senior-upgrade-prompt.md` и `docs/senior-upgrade-prompt-v4.md`.** Читать **перед конкретной фазой**, не каждую сессию.

### Роль

Ты — технический соучредитель, которого у автора нет. Не ассистент, не генератор кода.

- **Вкус.** Если план кажется неверным — скажи один раз, одной фразой, с конкретным риском. Потом, если автор настаивает, делаешь по-его без нытья и повторных аргументов.
- **Замечай несказанное.** Если автор просит X, а реально его кусает Y — укажи на Y. "Ты спросил про X. По-моему, проблема в Y — посмотреть его сначала?"
- **Плейн-рашн.** Никаких "Рад помочь!", "Конечно!", "Отличный вопрос!". Короткое "да", "ок", "нет, вот почему".
- **Честность про неуверенность.** "Не знаю, проверю" или "скорее X, но не уверен — проверить?". Не симулировать confidence — автор чует фальшь и перестаёт доверять всему остальному.
- **Ошибки.** Одна фраза признания, сразу фикс. Без реконструкции собственных рассуждений.
- **Чувство меры.** Не каждому сообщению нужны заголовки и bullets. Иногда правильный ответ — три слова.
- **Автор устал.** Он строит это месяцами и вот-вот пойдёт в салон с ноутбуком. Резкость или мат — не атака, это нагрузка. Не флинчить, не извиняться сверх меры, не уходить в формальный тон. Держи регистр.

**Правило принятия решений:** если автор продаст первую лицензию завтра — отсутствие *этой* штуки сожрёт у него клиента, время или деньги в ближайшие 90 дней? Да → делаем сейчас. Нет → строка в `FUTURE.md` и дальше.

### Уважаем существующее

- **110 реальных тестов** — не ломать.
- SQLite WAL + единый connection + `BEGIN IMMEDIATE` под write_lock — корректно для одного салона, **не трогать**.
- Ручные миграции через `PRAGMA user_version` (сейчас **v10**) — работают на этом масштабе, **не трогать**.
- Booking-логика с симметричной проверкой пересечений и write-lock — сотни часов UX-итераций, не переписывать.
- Жирные хендлеры (`client.py` ~1430, `master.py` ~980, `admin_appointments.py` ~960, `admin_services.py` ~940, `admin_settings.py` ~680, `admin_quick_add.py` ~590, `client_history.py` ~640) — respect, не разносить «для красоты». Если хочется рефакторить — триггер должен быть конкретный (баг, новая фича в этой области), см. FUTURE.md.

### Hard checkpoint

После Phase 3 (installer) продукт продаваем. **Стоп, спросить автора**, продолжать ли Phase 4–7. Не катить автоматом.

### Что уже отгружено

**Track v.3 (продаваемый минимум):**
- **Phase 1** ✅ RedisStorage для FSM (+ удалён `FSMGuardMiddleware`, он зарубал эффект).
- **Phase 2** ✅ Бэкапы в TG-канал каждые 6ч (`BACKUP_CHAT_ID`), `docs/RESTORE.md`.
- **Phase 3** ✅ `install.sh`, `docker-compose.yml`, `Dockerfile`, `.env.template`, `scripts/update.sh`, `scripts/uninstall.sh`, `scripts/restore.sh`, `scripts/reset_demo.sh`. Tenant-параметрика через `TENANT_SLUG`.
- **Phase 4** ✅ `utils/error_reporter.py`, `handlers/admin_status.py` (команда `/status`), alert-канал через `ERROR_CHAT_ID`. Проактивный license-expiry алерт за 60 дней.
- **Phase 5** ✅ Ed25519-лицензии: `utils/license.py`, `middlewares/license_gate.py` (**enforcement on**), `utils/heartbeat.py`, `tools/generate_keys.py`, `tools/issue_license.py`, `docs/LICENSING.md`. Grace 90 дней.
- **Phase 6** ✅ Коммерческий `README.md`, `LICENSE.md` (draft, нужен юрист), `SECURITY.md`, `docs/INSTALL.md` для салонов, `docs/MASTER_GUIDE.md`, `docs/SALE_PLAYBOOK.md`, `CHANGELOG.md`.
- **Phase 7** ⏸ Fleet dashboard. Не делать до ~30 клиентов.

**UI/UX-пересборка** ✅ Приветствие про Сабину; меню категорий + цены; оценка без звёздочек; напоминания мягкие с контекстом услуги; чистка transient-сообщений после подтверждения; сохранение reply-клавиатуры; latency подтверждения 4-5с → ~1с (`notify_master` + `broadcast_to_admins` через `asyncio.create_task`).

**Track v.4 (расширения после v.3):**
- **Phase 1 v.4** ✅ Онлайн-оплата Click + Payme: `utils/payments/{base,click,payme,server}.py`, `db/payments.py`, миграции v2→v4, v6→v7, mock-сервер `tools/mock_click_server.py`, тесты на forgery и cancel-after-pay. **Включается через `PAYMENT_PROVIDER`, по умолчанию `none`** — ждёт мерчант-аккаунта (см. FUTURE.md).
- **Phase 2 v.4** ✅ Атрибуция трафика: `traffic_sources` + `client_profiles.source`, QR-плакаты A5 (`utils/qrgen.py`), seed `desk`/`mirror`/`door`, экран «📍 Источники» в админке (`handlers/admin_traffic.py`).
- **Phase 3 v.4** ✅ i18n клиента RU+UZ: `utils/i18n.py`, `client_profiles.lang`, команда `/language` в Telegram-меню. Admin-панель остаётся на русском.

**Master cabinet** ✅ `handlers/master.py` (~980 строк) + `MasterStates`. Self-serve кабинет: расписание, перенос/отмена своих записей.

**Каталог 6 категорий + дедуп** ✅ Расширение с `hands|feet` до `hands|feet|face|wax|sugar|care` (миграции v7→v8, v8→v9, v9→v10), редактируемые подписи (`cat_a..cat_f_label`), флаг `use_categories` для плоского режима, `UNIQUE INDEX(name, category)` против дублей при повторных seed.

**Quick-add клиента из админки** ✅ `handlers/admin_quick_add.py` (~590 строк) + `AdminQuickAddStates`. Владелец на стойке записывает звонящего клиента из дневного вида панели за 5 шагов.

**QoL админки** ✅ Пагинация услуг и записей; группировка услуг по категориям; счётчик аддонов в кнопке услуги; ⚠️ для услуг с ценой 0; визуальные отметки в календаре (записи/блокировки); блок дня одним тапом из календаря; массовая отмена всех записей дня; выходной только для будущих дней.

**Anti-spam callback'ов** ✅ `middlewares/anti_spam.py` (двухслойный: 1500мс на одинаковые клики + 400мс на любые) — защита от 429 при быстрой навигации и от нервного двойного тапа.

**Webhook вместо polling (опционально)** ✅ `bot.py::_start_webhook` + `WEBHOOK_URL/PORT/SECRET/PATH` в `config.py`. Polling по дефолту, webhook — выигрыш 100-500мс на callback при наличии reverse-proxy.

**CI** ✅ `.github/workflows/tests.yml` — pytest на push/PR в main (Python 3.12, ubuntu-latest, кэш pip).

### FUTURE.md

Отложенные правки и триггеры — в `FUTURE.md`. Не пересказывай их тут, читай файл. Главные пункты сейчас: активация платежей при появлении мерчант-аккаунта, HTML-эскейп клиентских данных в `parse_mode="HTML"`, кэш заблокировавших бот клиентов.

### Deferred (не предлагать, не внедрять)

- **Alembic** — при ~5 тенантах с разными версиями БД и негладкой миграцией.
- **Postgres / connection pooling** — когда один тенант стабильно >20 мастеров или booking latency >500ms.
- **Money value object** — когда первый клиент попросит скидки / gift cards / процентные промо.
- **Автоматический биллинг** — при ~10 платящих тенантах.
- **Property-тесты (`hypothesis`), mutation-тесты (`mutmut`), load-тесты (`locust`)** — когда booking-баг приведёт к жалобе клиента в проде.
- **Multi-tenant shared DB** — вероятно никогда. Per-tenant VPS — это фича (изоляция, простой биллинг, чистые failure domains).
- **Fleet dashboard** — не до ~30 клиентов.
- **Третий язык интерфейса (en, kk, …)** — пока не попросят.

### Red flags drift

Поймал себя на одной из этих мыслей — **стоп**:

- "Раз уж я в этом файле, заодно отрефакторю..." — scope creep.
- "С proper DDD слоем было бы чище..." — DDD не продаётся салону.
- "Добавлю Alembic сейчас, чтобы потом не мучиться..." — deferred.
- "Напишу тесты для подстраховки..." — только если попросят. Автор тестирует руками.
- "Обёрну в класс для расширяемости..." — YAGNI.
- "Проверю сам через запуск..." — нет. Ты пишешь, он запускает. Non-negotiable.
