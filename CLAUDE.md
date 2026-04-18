# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Bot

```bash
# Запуск
python bot.py

# Установка зависимостей
pip install -r requirements.txt
```

Необходим файл `.env` с переменными:
```
BOT_TOKEN=<токен от @BotFather>
ADMIN_IDS=123456789,987654321  # Telegram user_id через запятую
```

## Architecture Overview

Telegram-бот записи на маникюр на **aiogram 3**, SQLite через **aiosqlite**, напоминания через **APScheduler**.

### Два режима пользователя

- **Клиент** — бронирует запись через FSM-цепочку: выбор услуги → дата → время → профиль → подтверждение.
- **Админ** — управляет записями, услугами, расписанием, статистикой через inline-панель.

Определение роли: `utils/admin.py:is_admin()` — проверяет `ADMIN_IDS` из `.env` **и** `_db_admins_cache` (runtime-кэш из таблицы `admins`). Кэш загружается при старте через `refresh_admins_cache()` и обновляется при добавлении/удалении через `handlers/admin_manage.py`.

### Порядок регистрации роутеров (критически важно)

`bot.py` регистрирует все admin-роутеры **до** `client.router`. Причина: `client.py` содержит catch-all `fallback_message`, который перехватил бы текстовые сообщения FSM-потоков администратора.

### База данных

Единый глобальный connection (`database._db`), открывается в `init_db()`, закрывается в `close_db()`. WAL-режим и `PRAGMA foreign_keys=ON` включены. **Не использовать `aiosqlite.connect()` напрямую** в новых функциях — только `get_db()`.

Таблицы: `appointments`, `services`, `settings`, `blocked_slots`, `client_profiles`, `sent_reminders`, `admin_logs`, `admins`.

`services.py` — только seed-данные для первого запуска (если таблица `services` пуста).

### FSM States

`states.py`: `BookingStates` (клиентский флоу), `AdminStates` (все FSM-потоки админа: редактирование услуг, перенос записей, настройки графика, блокировки).

### Планировщик напоминаний

`scheduler.py` — запускается каждые 15 минут. Два типа: `reminder_24h` (окно 20-28 ч до визита) и `reminder_2h` (окно 1.5-2.5 ч). Дедупликация через таблицу `sent_reminders`.

### Панель администратора

`utils/panel.py` — трекер «живого» сообщения-панели (один `message_id` на чат). `edit_panel()` редактирует это сообщение; при ошибке `TelegramBadRequest` — удаляет и создаёт заново. `asyncio.Lock` на каждый чат предотвращает дубли при быстрых кликах.

### Клавиатуры

`keyboards/inline.py` — все inline и reply клавиатуры. Callback-data форматы:
- `service_<id>`, `date_<YYYY-MM-DD>`, `time_<HH:MM>` — клиентский флоу
- `appt_detail_<id>`, `appt_status_<id>_<status>`, `appt_cancel_<id>` — управление записью
- `cal_day_<year>_<month>_<day>` — навигация по календарю
- `svc_*`, `block_*`, `settings_*` — управление услугами / блокировками / настройками

### Настройки графика

Хранятся в таблице `settings`: `work_start`, `work_end` (часы), `slot_step` (минуты). Читаются через `get_setting()` / `get_all_settings()`.

## Dev Preferences

- **Тесты**: не писать, если пользователь явно не попросил.
- **Коммиты**: не приоритет, проект локальный — не навязывать.
- **Верификация провалилась**: использовать `debug-context` скилл, диагностировать причину, предложить fix — не ждать решения пользователя.
