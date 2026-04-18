# Manicure Bot

Telegram-бот для записи на маникюр. Поддерживает несколько мастеров, гибкое расписание, напоминания и админ-панель.

## Стек

- **aiogram 3** — Telegram Bot API
- **aiosqlite** — SQLite (WAL, foreign keys)
- **APScheduler** — напоминания и бэкапы
- **openpyxl** — экспорт в Excel

## Возможности

### Клиент
- Запись через FSM-флоу: услуга → допы → мастер → дата → время → подтверждение
- Просмотр и отмена своих записей
- Напоминания за 24 ч и за 2 ч до визита
- Отзывы и рейтинги мастеров

### Админ
- Inline-панель с «живым» сообщением (одно на чат)
- Управление записями: статусы, перенос, отмена
- CRUD услуг и допов
- Управление мастерами и индивидуальным расписанием
- Блокировки времени (глобальные и по мастеру)
- Недельное расписание + точечные исключения
- Статистика и экспорт в Excel
- Несколько админов через `.env` или базу

## Запуск

```bash
pip install -r requirements.txt
python bot.py
```

Файл `.env`:

```
BOT_TOKEN=<токен от @BotFather>
ADMIN_IDS=123456789,987654321
DB_PATH=manicure.db
TZ=Europe/Moscow
```

## Тесты

```bash
pip install -r requirements-dev.txt
pytest
```

## Структура

```
bot.py                 точка входа
config.py              чтение .env
constants.py           бизнес-константы
scheduler.py           APScheduler: напоминания + бэкап
states.py              FSM states
db/                    слой данных (connection, appointments, masters, ...)
handlers/              роутеры aiogram (client, admin_*, reviews)
keyboards/inline.py    все клавиатуры
services/booking.py    генерация свободных слотов
utils/                 panel, admin, callbacks, ui, timezone, validators
middlewares/fsm_guard  сброс FSM после рестарта по session UUID
tests/                 pytest (86+ тестов)
```

## Ключевые архитектурные решения

- **Один глобальный SQLite-connection** + `write_lock` + `BEGIN IMMEDIATE` — атомарность бронирования.
- **Симметричный overlap-check** в одной транзакции — никаких гонок при конкурентной записи.
- **`FSMGuardMiddleware`** инвалидирует FSM из старой сессии по UUID — пользователь не «зависает» после рестарта бота.
- **Live-панель админа** — одно редактируемое сообщение на чат, `asyncio.Lock` против дублей при быстрых кликах.
- **Дедуп напоминаний** через `sent_reminders` с UNIQUE-констрейнтом — повторные пуши невозможны.
