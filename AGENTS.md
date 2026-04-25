# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Running the Bot

**Продакшн (docker):**
```bash
./install.sh <tenant_slug> <bot_token> <admin_id>   # первый деплой на VPS
docker compose up -d --build                        # обновление
./scripts/update.sh                                 # git pull + rebuild
./scripts/uninstall.sh                              # архив в /root + снос
```

**Локальная разработка:**
```bash
pip install -r requirements.txt
python bot.py
```

Необходим файл `.env` — для полного списка смотри `.env.template`. Минимум:
```
BOT_TOKEN=<токен от @BotFather>
ADMIN_IDS=123456789,987654321      # Telegram user_id через запятую
TENANT_SLUG=salon-slug             # [a-z0-9-]
REDIS_URL=redis://localhost:6379/0 # в docker: redis://redis:6379/0
```

Опциональные:
```
BACKUP_CHAT_ID=-100...       # приватный канал для бэкапов БД (каждые 6ч)
ERROR_CHAT_ID=-100...        # канал для алертов об unhandled exceptions
LICENSE_KEY=<blob>           # Ed25519-подписанный ключ от tools/issue_license.py
HEARTBEAT_URL=https://...    # эндпоинт для daily heartbeat-POST
LICENSE_CONTACT=@handle      # для сообщения "лицензия истекла, обратитесь к X"
```

## Architecture Overview

Telegram-бот записи на маникюр на **aiogram 3**, SQLite через **aiosqlite**, напоминания через **APScheduler**.

### Два режима пользователя

- **Клиент** — бронирует запись через FSM: **категория (ручки/ножки) → услуга с ценой → мастер → дата → время → имя → телефон → подтверждение.** После подтверждения transient-сообщения (вопросы имени/телефона/summary) удаляются, остаются только hero + blockquote + напоминалка.
- **Админ** — управляет записями, услугами, расписанием, статистикой через inline-панель + `/status` для быстрой диагностики.

Определение роли: `utils/admin.py:is_admin()` — проверяет `ADMIN_IDS` из `.env` **и** `_db_admins_cache` (runtime-кэш из таблицы `admins`). Кэш загружается при старте через `refresh_admins_cache()` и обновляется при добавлении/удалении через `handlers/admin_manage.py`.

### Порядок регистрации роутеров (критически важно)

`bot.py` регистрирует все admin-роутеры **до** `client.router`. Причина: `client.py` содержит catch-all `fallback_message`, который перехватил бы текстовые сообщения FSM-потоков администратора.

### База данных

Единый глобальный connection (`database._db`), открывается в `init_db()`, закрывается в `close_db()`. WAL-режим и `PRAGMA foreign_keys=ON` включены. **Не использовать `aiosqlite.connect()` напрямую** в новых функциях — только `get_db()`.

Таблицы: `appointments`, `services`, `settings`, `blocked_slots`, `client_profiles`, `sent_reminders`, `admin_logs`, `admins`, `masters`, `master_schedule`, `weekly_schedule`, `service_addons`, `appointment_addons`, `reviews`.

Миграции — ручные через `PRAGMA user_version`, см. `db/connection.py::init_db`:
- **v0→v1**: `appointments.cancel_reason`, `appointments.master_id`, `blocked_slots.master_id`.
- **v1→v2**: `services.category` (`'hands'` | `'feet'`), бэкфилл по имени.

`db/seed.py` — seed-данные для первого запуска (если таблица `services` пуста). Новые услуги должны иметь category.

**FSM-хранилище:** Redis через `REDIS_URL` (см. `bot.py::_build_storage`). Если REDIS_URL пуст или Redis недоступен — fallback на `MemoryStorage` (WARN в логах, бот не падает).

### FSM States

`states.py`:
- `BookingStates`: **choose_category** → choose_service → choose_addons → choose_master → choose_date → choose_time → confirm_profile → get_name → get_phone → confirm.
- `AdminStates`: редактирование услуг, добавление услуги (с шагом **service_add_category**), перенос записей, настройки графика, блокировки, мастера.

### Планировщик (scheduler.py)

Три задачи, все обёрнуты в `_safe_*` (unhandled exceptions уходят в `utils.error_reporter.report_error`):
- **send_reminders** — каждые 15 минут. Типы: `reminder_24h` (окно 20-28ч), `reminder_2h` (окно 1.5-2.5ч). Дедуп через `sent_reminders`.
- **run_backup** — каждые 6ч. Локальный `.db` в `./backups/` (ротация 7) + отправка в `BACKUP_CHAT_ID` если задан.
- **send_heartbeat** — каждые 24ч (+ раз при старте). POST `{tenant_slug, license_id, version, last_seen}` на `HEARTBEAT_URL` если задан. Ошибка отправки не блокирует бот.

### Error reporting

`utils/error_reporter.py` + `@dp.errors()` в `bot.py` — unhandled exceptions из хендлеров и scheduler-задач уходят в `ERROR_CHAT_ID` с тегом `[TENANT_SLUG]`, коротким контекстом и traceback'ом. Plus хранит `_last_error` и `_start_time` in-process для `/status`-команды.

### Licensing

`utils/license.py` — Ed25519-подписанные ключи. Публичный ключ вмёрзнут в `PUBLIC_KEY_PEM`, приватный — у автора в `license_private_key.pem` (gitignored). Режимы: `dev` (placeholder) / `ok` / `grace` (истекла ≤90 дн.) / `restricted`.

`middlewares/license_gate.py` — блокирует хендлеры в RESTRICTED режиме. **Зарегистрирован** в `bot.py` (см. строки 133-135). Без валидного `LICENSE_KEY` бот отвечает только на `/start`. В dev-режиме (`PUBLIC_KEY_PEM` = плейсхолдер) middleware пропускает всё.

Инструменты автора: `tools/generate_keys.py` (разово), `tools/issue_license.py` (на каждую продажу). Полный флоу в `docs/LICENSING.md`.

### Панель администратора

`utils/panel.py` — трекер «живого» сообщения-панели (один `message_id` на чат). `edit_panel()` редактирует это сообщение; при ошибке `TelegramBadRequest` — удаляет и создаёт заново. `asyncio.Lock` на каждый чат предотвращает дубли при быстрых кликах.

### Клавиатуры

`keyboards/inline.py` — все inline и reply клавиатуры. Callback-data форматы:
- `cat_hands`, `cat_feet`, `cat_back` — клиентский выбор категории
- `service_<id>`, `date_<YYYY-MM-DD>`, `time_<HH:MM>` — клиентский флоу
- `appt_detail_<id>`, `appt_status_<id>_<status>`, `appt_cancel_<id>` — управление записью
- `cal_day_<year>_<month>_<day>` — навигация по календарю
- `svc_*`, `svc_cat_*` — управление услугами и админский выбор категории
- `block_*`, `settings_*` — блокировки / настройки
- `rev_rate_<appt>_<1..5>`, `rev_*` — отзывы

Кнопки услуг содержат цену: `гель-лак · 150 000`. Префикс «маникюр/педикюр» срезается — категория уже выбрана. Цены без «сум», пробел-разделитель тысяч (`_price_short` в `inline.py`).

### Настройки графика

Хранятся в таблице `settings`: `work_start`, `work_end` (часы), `slot_step` (минуты). Читаются через `get_setting()` / `get_all_settings()`.

## Dev Preferences

- **Тесты**: не писать, если пользователь явно не попросил. 86+ интеграционных в `tests/` — не ломать.
- **Коммиты**: не оставлять локально. После коммита — сразу `git push origin main`. Не копить висящие коммиты на локале. Исключение — если автор явно сказал «не пушь».
- **Верификация провалилась**: использовать `debug-context` скилл, диагностировать причину, предложить fix — не ждать решения пользователя.
- **Пересборка после правок**: автор работает в docker. После изменения python-кода — `docker compose up -d --build`. После изменения только `.env` — обычно `docker compose up -d` достаточно, но с `--build` надёжнее.
- **Автор тестирует руками**. Не запускай `python bot.py` сам, не шли запросы в прод-бот. Только даёшь команды, он их выполняет.
- **Recap в конце сессии**. Когда задача или серия связанных работ закрыта (закоммичено, запушено, верификация прошла), написать итоговую строку в формате:
  `※ recap: <через + перечень доставленного>. Следующий шаг: <что дальше>. (disable recaps in /config)`
  Триггер — логическое завершение темы: ответ на «что дальше?», закрытие инцидента, push финального коммита. Не писать recap после каждого ответа — только в конце сессии/блока.

---

## Commercial Readiness Track

Продукт готовится к продаже реальным бьюти-салонам. Каждый салон — свой VPS, свой bot token, своя БД (**не** multi-tenant — изоляция намеренно выбрана над элегантностью). Автор сам продаёт, ставит и саппортит. Цель Year 1 — 80 салонов, не 400.

**Детали 7 фаз, verification-команды, don'ts — в `docs/senior-upgrade-prompt.md`.** Читать **перед конкретной фазой**, не каждую сессию.

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

- 86+ реальных тестов — не ломать.
- SQLite WAL + единый connection + `BEGIN IMMEDIATE` — корректно для одного салона, **не трогать**.
- Ручные миграции через `PRAGMA user_version` — работают на этом масштабе, **не трогать**.
- Booking-логика с симметричной проверкой пересечений и write-lock — сотни часов UX-итераций, не переписывать.
- 14 хендлеров, `admin_services.py` (~25KB), `client.py` (~36KB) — respect.

### Hard checkpoint

После Phase 3 (installer) продукт продаваем. **Стоп, спросить автора**, продолжать ли Phase 4–7. Не катить автоматом.

### Что уже отгружено (ночь 2026-04-19)

- **Phase 1** ✅ RedisStorage для FSM (+ удалён `FSMGuardMiddleware`, он зарубал эффект).
- **Phase 2** ✅ Бэкапы в TG-канал каждые 6ч (`BACKUP_CHAT_ID`), `docs/RESTORE.md`.
- **Phase 3** ✅ `install.sh`, `docker-compose.yml`, `Dockerfile`, `.env.template`, `scripts/update.sh`, `scripts/uninstall.sh`. Tenant-параметрика через `TENANT_SLUG`.
- **Phase 4** ✅ `utils/error_reporter.py`, `handlers/admin_status.py` (команда `/status`), alert-канал через `ERROR_CHAT_ID`.
- **Phase 5** ✅ Ed25519-лицензии: `utils/license.py`, `middlewares/license_gate.py` (**enforcement on**, gate зарегистрирован в `bot.py:133-135`), `utils/heartbeat.py`, `tools/generate_keys.py`, `tools/issue_license.py`, `docs/LICENSING.md`. Grace 90 дней.
- **Phase 6** ✅ Коммерческий `README.md`, `LICENSE.md` (draft, нужен юрист), `SECURITY.md`, `docs/INSTALL.md` для салонов, `CHANGELOG.md`.
- **UI-пересборка** ✅ Приветствие про Сабину; меню категорий + цены; оценка без звёздочек; напоминания мягкие с контекстом услуги; чистка transient-сообщений после подтверждения; сохранение reply-клавиатуры; latency подтверждения 4-5с → ~1с (notify_master + broadcast_to_admins → `asyncio.create_task`).

- **Phase 7** ⏸ Fleet dashboard. Не делать до ~30 клиентов.

### FUTURE.md

Отложенные правки и триггеры — в `FUTURE.md`. Не пересказывай их тут, читай файл.

### Deferred (не предлагать, не внедрять)

- **Alembic** — при ~5 тенантах.
- **Postgres / connection pooling** — когда один тенант стабильно >20 мастеров или booking latency >500ms.
- **Money value object** — когда первый клиент попросит скидки / gift cards / процентные промо.
- **Автоматический биллинг** — при ~10 платящих тенантах.
- **Property-тесты (`hypothesis`), mutation-тесты (`mutmut`), load-тесты (`locust`)** — когда booking-баг приведёт к жалобе клиента в проде.
- **Multi-tenant shared DB** — вероятно никогда. Per-tenant VPS — это фича (изоляция, простой биллинг, чистые failure domains).
- **i18n** — при первом не-русскоязычном клиенте.

### Red flags drift

Поймал себя на одной из этих мыслей — **стоп**:

- "Раз уж я в этом файле, заодно отрефакторю..." — scope creep.
- "С proper DDD слоем было бы чище..." — DDD не продаётся салону.
- "Добавлю Alembic сейчас, чтобы потом не мучиться..." — deferred.
- "Напишу тесты для подстраховки..." — только если попросят. Автор тестирует руками.
- "Обёрну в класс для расширяемости..." — YAGNI.
- "Проверю сам через запуск..." — нет. Ты пишешь, он запускает. Non-negotiable.
