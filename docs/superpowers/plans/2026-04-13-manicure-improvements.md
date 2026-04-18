# Manicure Bot Improvements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 13 улучшений: рефакторинг database.py, timezone, race condition fix, FSM graceful degradation, deeplink оплата, повторная запись после отзыва, уведомления мастеру, статистика по мастерам, показ отзывов клиентам, дедупликация MONTHS_SHORT, консолидация format_date_ru, аудит мастеров.

**Architecture:** Рефакторинг database.py → пакет `db/` с реэкспортом через `__init__.py`. Timezone через `ZoneInfo("Asia/Tashkent")` в `config.py`. Race condition — через `BEGIN IMMEDIATE` транзакцию. Новые фичи добавляются в существующие handler-файлы.

**Tech Stack:** Python 3.12, aiogram 3.7, aiosqlite, APScheduler, openpyxl

---

### Task 1: Рефакторинг database.py → пакет db/

**Files:**
- Create: `db/__init__.py`
- Create: `db/connection.py`
- Create: `db/appointments.py`
- Create: `db/services.py`
- Create: `db/masters.py`
- Create: `db/clients.py`
- Create: `db/settings.py`
- Create: `db/reminders.py`
- Create: `db/reviews.py`
- Create: `db/admin.py`
- Create: `db/helpers.py`
- Delete: `database.py`
- Modify: `bot.py` (import init_db, close_db from db)

**Принцип разбиения:**
- `connection.py` — `get_db()`, `close_db()`, `init_db()`, `_dict_rows()`, `_dict_row()`, создание таблиц
- `appointments.py` — все функции CRUD записей: `get_booked_times`, `is_slot_free`, `create_appointment`, `get_appointments_by_date`, `get_appointments_by_date_full`, `get_appointment_by_id`, `update_appointment_status`, `reschedule_appointment`, `get_appointments_by_phone`, `get_upcoming_appointments`, `get_client_appointments`, `cancel_appointment_by_client`, `get_all_future_appointments`, `get_stats`, `get_appointments_for_export`
- `services.py` — `get_services`, `get_service_by_id`, `update_service_*`, `toggle_service_active`, `delete_service`, `add_service`, `get_addons_for_service`, `get_addon_by_id`, `add_addon`, `delete_addon`, `toggle_addon_active`, `service_has_future_appointments`
- `masters.py` — `get_active_masters`, `get_all_masters`, `get_master`, `create_master`, `update_master`, `toggle_master_active`, `seed_master_schedule`, `get_master_schedule`, `get_day_schedule_for_master`, `get_day_off_weekdays_for_master`, `get_time_blocks_for_master`
- `clients.py` — `get_client_profile`, `save_client_profile`, `get_recent_clients`, `search_clients`, `get_dormant_clients`, `get_client_card`
- `settings.py` — `get_setting`, `set_setting`, `get_all_settings`, `get_weekly_schedule`, `get_day_schedule`, `update_weekday_schedule`, `is_day_off`, `get_time_blocks`, `get_future_blocks`, `add_day_off`, `add_time_block`, `delete_blocked_slot`
- `reminders.py` — `was_reminder_sent`, `mark_reminder_sent`
- `reviews.py` — `save_review`, `get_review_by_appointment`, `get_reviews_stats`
- `admin.py` — `log_admin_action`, `get_admin_logs`, `add_admin`, `remove_admin`, `get_db_admins`, `is_db_admin`
- `helpers.py` — `_price_fmt`

- [ ] **Step 1: Создать `db/connection.py`**

Скопировать из `database.py`: импорты, `_db`, `_db_ready`, `get_db()`, `close_db()`, `_dict_rows()`, `_dict_row()`, `init_db()`.

```python
"""
Единый модуль подключения к БД.
Один глобальный connection, WAL-режим, foreign_keys=ON.
"""
import logging
from datetime import datetime
from typing import Any, Iterable

import aiosqlite

from config import DB_PATH
from constants import DEFAULT_SETTINGS
from services import SERVICES

logger = logging.getLogger(__name__)

_db: aiosqlite.Connection | None = None
_db_ready: bool = False


async def get_db() -> aiosqlite.Connection:
    # ... (точная копия из database.py:31-39)


async def close_db() -> None:
    # ... (точная копия из database.py:43-53)


async def _dict_rows(sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    # ... (точная копия из database.py:56-72)


async def _dict_row(sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
    # ... (точная копия из database.py:76-87)


async def init_db() -> None:
    # ... (точная копия из database.py:90-323, все CREATE TABLE и миграции)
```

- [ ] **Step 2: Создать `db/helpers.py`**

```python
def _price_fmt(price: int) -> str:
    """Форматирование цены: 250000 → 250 000"""
    return f"{price:,}".replace(",", " ")
```

- [ ] **Step 3: Создать `db/appointments.py`**

Перенести все функции работы с записями. Каждая начинается с `from db.connection import get_db, _dict_rows, _dict_row`.

- [ ] **Step 4: Создать `db/services.py`**

Перенести все функции работы с услугами и аддонами.

- [ ] **Step 5: Создать `db/masters.py`**

Перенести все функции работы с мастерами и расписаниями мастеров.

- [ ] **Step 6: Создать `db/clients.py`**

Перенести функции профилей клиентов и поиска.

- [ ] **Step 7: Создать `db/settings.py`**

Перенести настройки, weekly_schedule, blocked_slots.

- [ ] **Step 8: Создать `db/reminders.py`**

Перенести `was_reminder_sent`, `mark_reminder_sent`.

- [ ] **Step 9: Создать `db/reviews.py`**

Перенести `save_review`, `get_review_by_appointment`, `get_reviews_stats`.

- [ ] **Step 10: Создать `db/admin.py`**

Перенести `log_admin_action`, `get_admin_logs`, `add_admin`, `remove_admin`, `get_db_admins`, `is_db_admin`.

- [ ] **Step 11: Создать `db/__init__.py` — реэкспорт всех публичных функций**

```python
"""
Пакет работы с БД.
Реэкспорт для обратной совместимости: `from db import get_services` работает.
"""
from db.connection import init_db, close_db, get_db
from db.helpers import _price_fmt
from db.appointments import (
    get_booked_times, is_slot_free, create_appointment,
    get_appointments_by_date, get_appointments_by_date_full,
    get_appointment_by_id, update_appointment_status,
    reschedule_appointment, get_appointments_by_phone,
    get_upcoming_appointments, get_client_appointments,
    cancel_appointment_by_client, get_all_future_appointments,
    get_stats, get_appointments_for_export,
)
from db.services import (
    get_services, get_service_by_id,
    update_service_name, update_service_price,
    update_service_duration, update_service_description,
    toggle_service_active, delete_service, add_service,
    get_addons_for_service, get_addon_by_id, add_addon,
    delete_addon, toggle_addon_active, service_has_future_appointments,
)
from db.masters import (
    get_active_masters, get_all_masters, get_master,
    create_master, update_master, toggle_master_active,
    seed_master_schedule, get_master_schedule,
    get_day_schedule_for_master, get_day_off_weekdays_for_master,
    get_time_blocks_for_master,
)
from db.clients import (
    get_client_profile, save_client_profile,
    get_recent_clients, search_clients,
    get_dormant_clients, get_client_card,
)
from db.settings import (
    get_setting, set_setting, get_all_settings,
    get_weekly_schedule, get_day_schedule, update_weekday_schedule,
    is_day_off, get_time_blocks, get_future_blocks,
    add_day_off, add_time_block, delete_blocked_slot,
)
from db.reminders import was_reminder_sent, mark_reminder_sent
from db.reviews import save_review, get_review_by_appointment, get_reviews_stats
from db.admin import (
    log_admin_action, get_admin_logs,
    add_admin, remove_admin, get_db_admins, is_db_admin,
)

__all__ = [
    # connection
    "init_db", "close_db", "get_db",
    # helpers
    "_price_fmt",
    # appointments
    "get_booked_times", "is_slot_free", "create_appointment",
    "get_appointments_by_date", "get_appointments_by_date_full",
    "get_appointment_by_id", "update_appointment_status",
    "reschedule_appointment", "get_appointments_by_phone",
    "get_upcoming_appointments", "get_client_appointments",
    "cancel_appointment_by_client", "get_all_future_appointments",
    "get_stats", "get_appointments_for_export",
    # services
    "get_services", "get_service_by_id",
    "update_service_name", "update_service_price",
    "update_service_duration", "update_service_description",
    "toggle_service_active", "delete_service", "add_service",
    "get_addons_for_service", "get_addon_by_id", "add_addon",
    "delete_addon", "toggle_addon_active", "service_has_future_appointments",
    # masters
    "get_active_masters", "get_all_masters", "get_master",
    "create_master", "update_master", "toggle_master_active",
    "seed_master_schedule", "get_master_schedule",
    "get_day_schedule_for_master", "get_day_off_weekdays_for_master",
    "get_time_blocks_for_master",
    # clients
    "get_client_profile", "save_client_profile",
    "get_recent_clients", "search_clients",
    "get_dormant_clients", "get_client_card",
    # settings
    "get_setting", "set_setting", "get_all_settings",
    "get_weekly_schedule", "get_day_schedule", "update_weekday_schedule",
    "is_day_off", "get_time_blocks", "get_future_blocks",
    "add_day_off", "add_time_block", "delete_blocked_slot",
    # reminders
    "was_reminder_sent", "mark_reminder_sent",
    # reviews
    "save_review", "get_review_by_appointment", "get_reviews_stats",
    # admin
    "log_admin_action", "get_admin_logs",
    "add_admin", "remove_admin", "get_db_admins", "is_db_admin",
]
```

- [ ] **Step 12: Обновить все импорты в проекте**

Заменить `from database import ...` → `from db import ...` во всех файлах:
- `bot.py`
- `scheduler.py`
- `handlers/client.py`
- `handlers/admin.py`
- `handlers/admin_appointments.py`
- `handlers/admin_blocks.py`
- `handlers/admin_clients.py`
- `handlers/admin_export.py`
- `handlers/admin_manage.py`
- `handlers/admin_masters.py`
- `handlers/admin_services.py`
- `handlers/admin_settings.py`
- `handlers/admin_stats.py`
- `handlers/reviews.py`
- `utils/admin.py`

- [ ] **Step 13: Удалить `database.py`**

- [ ] **Step 14: Проверить запуск**

Run: `cd /c/Users/eleru/PycharmProjects/manicure && python -c "from db import init_db, close_db, get_services, _price_fmt; print('OK')"`
Expected: `OK`

---

### Task 2: Дедупликация MONTHS_SHORT и консолидация format_date_ru

**Files:**
- Modify: `constants.py` — добавить `format_date_short_ru()`
- Modify: `handlers/admin.py` — заменить хардкод MONTHS_SHORT на `MONTHS_SHORT_RU` из constants
- Modify: `scheduler.py` — использовать `format_date_ru` из constants вместо локальной `_format_date_ru`
- Modify: `handlers/client.py` — использовать `format_date_ru` из constants

- [ ] **Step 1: Добавить `format_date_short_ru()` в constants.py**

```python
def format_date_short_ru(date_str: str) -> str:
    """Форматирует YYYY-MM-DD → '15 янв'. Для компактных списков."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.day} {MONTHS_SHORT_RU[dt.month - 1]}"
    except ValueError:
        return date_str
```

Добавить импорт `from datetime import datetime` в constants.py (уже не нужен — `format_date_ru` уже принимает int, но новая функция принимает строку).

- [ ] **Step 2: Заменить хардкод в handlers/admin.py**

В функциях `cb_notif_all_appointments`, `cb_admin_all_appointments`, `msg_all_appointments` — заменить:
```python
MONTHS_SHORT = ["янв","фев","мар","апр","май","июн","июл","авг","сен","окт","ноя","дек"]
# ...
date_label = f"{dt.day} {MONTHS_SHORT[dt.month - 1]}"
```
на:
```python
from constants import format_date_short_ru
# ...
date_label = format_date_short_ru(a["date"])
```
Убрать блок `try/except ValueError` вокруг `datetime.strptime` — `format_date_short_ru` сама обрабатывает ошибки.

- [ ] **Step 3: Заменить `_format_date_ru` в scheduler.py**

Удалить локальную `_format_date_ru()` (строки 35-41), заменить на:
```python
from constants import format_date_ru, MONTHS_RU
```
Использование в `_send_24h_reminder`: заменить `date_str = _format_date_ru(date)` на:
```python
try:
    dt = datetime.strptime(date, "%Y-%m-%d")
    date_str = format_date_ru(dt.day, dt.month)
except ValueError:
    date_str = date
```

- [ ] **Step 4: Проверить**

Run: `python -c "from constants import format_date_short_ru, format_date_ru; print(format_date_short_ru('2026-04-13'), format_date_ru(13, 4))"`
Expected: `13 апр 13 апреля`

---

### Task 3: Timezone awareness

**Files:**
- Modify: `config.py` — добавить `TZ`
- Modify: `constants.py` — добавить `now_local()`
- Modify: `handlers/client.py` — заменить `datetime.now()` на `now_local()`
- Modify: `scheduler.py` — заменить `datetime.now()` на `now_local()`
- Modify: `db/appointments.py` — заменить `datetime.now()` в `get_stats()`
- Modify: `keyboards/inline.py` — заменить `datetime.now()` в `dates_keyboard()`

- [ ] **Step 1: Добавить TZ в config.py и now_local в constants.py**

В `config.py`:
```python
from zoneinfo import ZoneInfo
TZ: Final[ZoneInfo] = ZoneInfo("Asia/Tashkent")
```

В `constants.py`:
```python
from datetime import datetime
from config import TZ

def now_local() -> datetime:
    """Текущее время в часовом поясе бота (Asia/Tashkent)."""
    return datetime.now(TZ)
```

- [ ] **Step 2: Заменить `datetime.now()` во всех файлах**

Поиск: `datetime.now()` — заменить на `now_local()` из constants.

Файлы:
- `handlers/client.py:127` — `generate_free_slots` (now = datetime.now())
- `keyboards/inline.py:43` — `dates_keyboard` (today = datetime.now())
- `scheduler.py:51` — `send_reminders` (now = datetime.now())
- `db/appointments.py` — `get_stats` (today = datetime.now().strftime(...))

В каждом файле добавить `from constants import now_local`.

- [ ] **Step 3: Проверить**

Run: `python -c "from constants import now_local; print(now_local())"`
Expected: текущая дата/время с tzinfo=Asia/Tashkent

---

### Task 4: Race condition fix в create_appointment

**Files:**
- Modify: `db/appointments.py` — обернуть check+insert в `BEGIN IMMEDIATE`

- [ ] **Step 1: Изменить `create_appointment()`**

Заменить текущую логику (отдельный SELECT COUNT + INSERT) на единую транзакцию:

```python
async def create_appointment(
    user_id: int, name: str, phone: str,
    service_id: int, service_name: str, service_duration: int,
    service_price: int, date: str, time: str,
    master_id: int | None = None,
) -> None:
    """Создаёт запись атомарно. Бросает ValueError если слот занят."""
    db = await get_db()
    # BEGIN IMMEDIATE блокирует БД на запись — другой writer ждёт
    await db.execute("BEGIN IMMEDIATE")
    try:
        if master_id is not None:
            cursor = await db.execute(
                """SELECT COUNT(*) FROM appointments
                   WHERE date = ? AND master_id = ? AND status = 'scheduled'
                     AND time < ?
                     AND datetime(date || ' ' || time, '+' || service_duration || ' minutes')
                         > datetime(date || ' ' || ?)
                """,
                (date, master_id, time, time),
            )
        else:
            cursor = await db.execute(
                """SELECT COUNT(*) FROM appointments
                   WHERE date = ? AND status = 'scheduled'
                     AND time < ?
                     AND datetime(date || ' ' || time, '+' || service_duration || ' minutes')
                         > datetime(date || ' ' || ?)
                """,
                (date, time, time),
            )
        count = (await cursor.fetchone())[0]
        if count > 0:
            await db.execute("ROLLBACK")
            raise ValueError("Этот слот уже занят. Выберите другое время.")

        await db.execute(
            """INSERT INTO appointments
               (user_id, name, phone, service_id, service_name, service_duration,
                service_price, date, time, status, master_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', ?)""",
            (user_id, name, phone, service_id, service_name, service_duration,
             service_price, date, time, master_id),
        )
        await db.execute("COMMIT")
    except ValueError:
        raise
    except Exception:
        await db.execute("ROLLBACK")
        raise
```

- [ ] **Step 2: Проверить синтаксис**

Run: `python -c "from db.appointments import create_appointment; print('OK')"`
Expected: `OK`

---

### Task 5: Graceful degradation FSM (middleware)

**Files:**
- Create: `middlewares/__init__.py`
- Create: `middlewares/fsm_guard.py`
- Modify: `bot.py` — подключить middleware

- [ ] **Step 1: Создать `middlewares/fsm_guard.py`**

```python
"""
Middleware: если пользователь в FSM-состоянии, но данные потерялись
(рестарт бота при MemoryStorage), мягко сбросить состояние.
"""
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, TelegramObject

logger = logging.getLogger(__name__)


class FSMGuardMiddleware(BaseMiddleware):
    """
    Проверяет: если state != None, но data пустой — скорее всего
    бот перезапустился и MemoryStorage потерял данные.
    Сбрасываем state и мягко сообщаем пользователю.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        state: FSMContext | None = data.get("state")
        if state is None:
            return await handler(event, data)

        current_state = await state.get_state()
        if current_state is None:
            return await handler(event, data)

        fsm_data = await state.get_data()
        if fsm_data:
            return await handler(event, data)

        # State есть, но данных нет — потеря после рестарта
        logger.info(
            "FSM state=%s with empty data, resetting (likely bot restart)",
            current_state,
        )
        await state.clear()

        if isinstance(event, Message):
            await event.answer(
                "Бот был перезапущен. Пожалуйста, начните заново: /start"
            )
        elif isinstance(event, CallbackQuery):
            await event.answer(
                "Бот был перезапущен. Нажмите /start",
                show_alert=True,
            )

        return  # не вызываем handler — пользователь начнёт заново
```

- [ ] **Step 2: Создать `middlewares/__init__.py`**

```python
```

- [ ] **Step 3: Подключить в bot.py**

После `dp = Dispatcher(...)`:
```python
from middlewares.fsm_guard import FSMGuardMiddleware
dp.message.middleware(FSMGuardMiddleware())
dp.callback_query.middleware(FSMGuardMiddleware())
```

- [ ] **Step 4: Проверить импорт**

Run: `python -c "from middlewares.fsm_guard import FSMGuardMiddleware; print('OK')"`
Expected: `OK`

---

### Task 6: Deeplink оплата (Click/Payme)

**Files:**
- Modify: `config.py` — опциональные `CLICK_URL`, `PAYME_URL`
- Modify: `keyboards/inline.py` — добавить `payment_keyboard()`
- Modify: `handlers/client.py` — после подтверждения записи показать кнопку оплаты

- [ ] **Step 1: Добавить настройки оплаты в config.py**

```python
# Deeplink для оплаты (опционально). Если не задано — кнопка оплаты не показывается.
PAYMENT_URL: Final[str | None] = os.getenv("PAYMENT_URL") or None
PAYMENT_LABEL: Final[str] = os.getenv("PAYMENT_LABEL", "Оплатить")
```

`.env` пример:
```
PAYMENT_URL=https://my.click.uz/services/pay?service_id=XXX&merchant_id=YYY&amount={amount}&transaction_param={appt_id}
```

- [ ] **Step 2: Добавить `payment_keyboard()` в keyboards/inline.py**

```python
def payment_keyboard(appt_id: int, amount: int) -> InlineKeyboardMarkup | None:
    """Клавиатура с deeplink на оплату. None если PAYMENT_URL не настроен."""
    from config import PAYMENT_URL, PAYMENT_LABEL
    if not PAYMENT_URL:
        return None
    url = PAYMENT_URL.replace("{amount}", str(amount)).replace("{appt_id}", str(appt_id))
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💳 {PAYMENT_LABEL}", url=url)],
        [InlineKeyboardButton(text="📋 Мои записи", callback_data="client_my_appointments")],
    ])
```

- [ ] **Step 3: Добавить кнопку оплаты после подтверждения записи**

В `handlers/client.py`, в `confirm_yes()` после успешного `create_appointment`, перед финальным сообщением — получить `appt_id` из последней вставки и добавить кнопку:

Модификация: после `await save_client_profile(...)` добавить:
```python
from keyboards.inline import payment_keyboard
pay_kb = payment_keyboard(appt_id, data["service_price"])
```

Для получения `appt_id` — изменить `create_appointment()` чтобы возвращала `int`:
```python
async def create_appointment(...) -> int:
    # ... существующий код ...
    cursor = await db.execute("INSERT INTO appointments ...", ...)
    await db.execute("COMMIT")
    return cursor.lastrowid
```

В финальном сообщении клиенту — если `pay_kb` не None, отправить дополнительное сообщение:
```python
if pay_kb:
    await callback.message.answer(
        f"💳 Оплатите запись онлайн:",
        reply_markup=pay_kb,
    )
```

- [ ] **Step 4: Проверить**

Run: `python -c "from keyboards.inline import payment_keyboard; print(payment_keyboard(1, 250000))"`
Expected: `None` (PAYMENT_URL не задан)

---

### Task 7: Повторная запись после отзыва

**Files:**
- Modify: `handlers/reviews.py` — после отзыва показать кнопку «Записаться снова»

- [ ] **Step 1: Добавить кнопку в `cb_review_skip` и `review_comment_text`**

В `cb_review_skip()`:
```python
@router.callback_query(F.data.regexp(r"^rev_skip_(\d+)$"))
async def cb_review_skip(callback: CallbackQuery, state: FSMContext):
    appt_id = int(callback.data.split("_")[2])
    await state.clear()
    try:
        await callback.message.edit_text(
            "Спасибо за отзыв! 🙏",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="🔁 Записаться снова",
                    callback_data=f"quick_rebook_{appt_id}",
                ),
            ]]),
        )
    except TelegramBadRequest:
        pass
    await callback.answer()
```

В `review_comment_text()`:
```python
@router.message(ReviewStates.enter_comment)
async def review_comment_text(message: Message, state: FSMContext):
    data = await state.get_data()
    appt_id = data.get("review_appt_id")
    comment = message.text.strip() if message.text else ""

    if appt_id and comment:
        existing = await get_review_by_appointment(appt_id)
        if existing:
            await save_review(appt_id, message.from_user.id, existing["rating"], comment)

    await state.clear()
    await message.answer(
        "Спасибо за отзыв! 🙏",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="🔁 Записаться снова",
                callback_data=f"quick_rebook_{appt_id}",
            ),
        ]]) if appt_id else None,
    )
```

Добавить импорты:
```python
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
```

- [ ] **Step 2: Проверить**

Run: `python -c "from handlers.reviews import router; print('OK')"`
Expected: `OK`

---

### Task 8: Уведомления мастеру о новой записи

**Статус:** Уже реализовано в `handlers/client.py:903-918` (новая запись) и строки 389-404 (отмена). Проверить полноту.

**Files:**
- Modify: `handlers/admin_appointments.py` — уведомлять мастера при изменении статуса и переносе

- [ ] **Step 1: Уведомление мастеру при изменении статуса**

В `handlers/admin_appointments.py`, найти обработчик изменения статуса (`appt_status_*` callback) и добавить уведомление мастеру:

```python
# После update_appointment_status:
if appt.get("master_id"):
    from db import get_master
    master = await get_master(appt["master_id"])
    if master and master.get("user_id") and master["user_id"] not in ADMIN_IDS:
        status_text = {"completed": "✅ Выполнено", "no_show": "🚫 Не пришёл", "cancelled": "❌ Отменено"}
        try:
            await callback.bot.send_message(
                master["user_id"],
                f"📋 <b>Статус записи изменён</b>\n\n"
                f"👤 {appt['name']}\n"
                f"📅 {appt['date']} в {appt['time']}\n"
                f"💅 {appt['service_name']}\n\n"
                f"Новый статус: {status_text.get(new_status, new_status)}",
                parse_mode="HTML",
            )
        except Exception:
            logger.warning("Не удалось уведомить мастера user_id=%s", master["user_id"])
```

- [ ] **Step 2: Уведомление мастеру при переносе**

В обработчике переноса записи (после `reschedule_appointment`):
```python
if appt.get("master_id"):
    from db import get_master
    master = await get_master(appt["master_id"])
    if master and master.get("user_id") and master["user_id"] not in ADMIN_IDS:
        try:
            await callback.bot.send_message(
                master["user_id"],
                f"🔄 <b>Запись перенесена</b>\n\n"
                f"👤 {appt['name']}\n"
                f"💅 {appt['service_name']}\n"
                f"📅 Новая дата: {new_date} в {new_time}",
                parse_mode="HTML",
            )
        except Exception:
            logger.warning("Не удалось уведомить мастера о переносе user_id=%s", master["user_id"])
```

---

### Task 9: Статистика по мастерам

**Files:**
- Modify: `db/appointments.py` — добавить `get_stats_by_master()`
- Modify: `handlers/admin_stats.py` — показать разбивку по мастерам
- Modify: `keyboards/inline.py` — кнопка «По мастерам»

- [ ] **Step 1: Добавить `get_stats_by_master()` в db/appointments.py**

```python
async def get_stats_by_master() -> list[dict[str, Any]]:
    """Статистика по каждому мастеру: записи, выручка, рейтинг."""
    return await _dict_rows(
        """SELECT m.id, m.name,
                  COUNT(CASE WHEN a.status = 'completed' THEN 1 END) AS completed,
                  COUNT(CASE WHEN a.status = 'scheduled' THEN 1 END) AS scheduled,
                  COUNT(CASE WHEN a.status = 'cancelled' THEN 1 END) AS cancelled,
                  COALESCE(SUM(CASE WHEN a.status = 'completed' THEN a.service_price END), 0) AS revenue,
                  ROUND(AVG(CASE WHEN r.rating IS NOT NULL THEN r.rating END), 1) AS avg_rating,
                  COUNT(r.id) AS reviews_count
           FROM masters m
           LEFT JOIN appointments a ON a.master_id = m.id
           LEFT JOIN reviews r ON r.appointment_id = a.id
           WHERE m.is_active = 1
           GROUP BY m.id
           ORDER BY revenue DESC"""
    )
```

- [ ] **Step 2: Добавить реэкспорт в db/__init__.py**

```python
from db.appointments import ..., get_stats_by_master
```

- [ ] **Step 3: Добавить обработчик в admin_stats.py**

```python
@router.callback_query(F.data == "stats_by_master")
async def cb_stats_by_master(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return

    from db import get_stats_by_master, _price_fmt
    stats = await get_stats_by_master()

    if not stats:
        try:
            await callback.message.edit_text("Нет данных по мастерам.")
        except TelegramBadRequest:
            pass
        await callback.answer()
        return

    lines = ["📊 <b>Статистика по мастерам</b>\n"]
    for s in stats:
        rating_str = f"{s['avg_rating']} ⭐ ({s['reviews_count']})" if s["avg_rating"] else "—"
        lines.append(
            f"\n👨‍🎨 <b>{s['name']}</b>\n"
            f"   ✅ {s['completed']} выполнено · 🕐 {s['scheduled']} ожидает · ❌ {s['cancelled']} отмен\n"
            f"   💰 {_price_fmt(s['revenue'])} сум · ⭐ {rating_str}"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="← Общая статистика", callback_data="admin_stats"),
    ]])

    try:
        await callback.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()
```

- [ ] **Step 4: Добавить кнопку в admin_stats.py**

В `cb_admin_stats`, изменить `export_kb`:
```python
export_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="👨‍🎨 По мастерам", callback_data="stats_by_master")],
    [InlineKeyboardButton(text="📥 Экспорт в Excel", callback_data="admin_export")],
])
```

---

### Task 10: Показ отзывов клиентам

**Files:**
- Modify: `db/reviews.py` — добавить `get_master_avg_rating()`
- Modify: `keyboards/inline.py` — показать рейтинг рядом с именем мастера
- Modify: `handlers/client.py` — при выборе мастера показать рейтинг

- [ ] **Step 1: Добавить `get_master_avg_rating()` в db/reviews.py**

```python
async def get_master_avg_rating(master_id: int) -> dict[str, Any]:
    """Средний рейтинг мастера."""
    row = await _dict_row(
        """SELECT ROUND(AVG(r.rating), 1) as avg_rating, COUNT(r.id) as total
           FROM reviews r
           JOIN appointments a ON a.id = r.appointment_id
           WHERE a.master_id = ?""",
        (master_id,),
    )
    return {
        "avg_rating": row["avg_rating"] if row and row["avg_rating"] else 0.0,
        "total": row["total"] if row else 0,
    }


async def get_all_masters_ratings() -> dict[int, dict[str, Any]]:
    """Рейтинги всех мастеров: {master_id: {avg_rating, total}}."""
    rows = await _dict_rows(
        """SELECT a.master_id,
                  ROUND(AVG(r.rating), 1) as avg_rating,
                  COUNT(r.id) as total
           FROM reviews r
           JOIN appointments a ON a.id = r.appointment_id
           WHERE a.master_id IS NOT NULL
           GROUP BY a.master_id"""
    )
    return {
        r["master_id"]: {"avg_rating": r["avg_rating"], "total": r["total"]}
        for r in rows
    }
```

- [ ] **Step 2: Реэкспорт в db/__init__.py**

Добавить `get_master_avg_rating`, `get_all_masters_ratings` в реэкспорт.

- [ ] **Step 3: Показать рейтинг при выборе мастера**

В `keyboards/inline.py`, изменить `masters_keyboard()` чтобы принимать рейтинги:

```python
def masters_keyboard(
    masters: list[dict],
    ratings: dict[int, dict] | None = None,
) -> InlineKeyboardMarkup:
    buttons = []
    ratings = ratings or {}
    for m in masters:
        r = ratings.get(m["id"])
        rating_str = f" · {r['avg_rating']}⭐" if r and r["avg_rating"] else ""
        buttons.append([InlineKeyboardButton(
            text=f"{m['name']}{rating_str}",
            callback_data=f"master_{m['id']}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
```

- [ ] **Step 4: Передать рейтинги в _show_master_step**

В `handlers/client.py`, в `_show_master_step()`:
```python
from db import get_all_masters_ratings
ratings = await get_all_masters_ratings()
# ...
reply_markup=masters_keyboard(masters, ratings),
```

---

### Task 11: Graceful shutdown — сообщение пользователям в активных FSM

**Files:**
- Modify: `bot.py` — перед остановкой отправить сообщение активным пользователям

Замечание: `MemoryStorage` не даёт доступа к списку всех активных states. Это ограничение самого хранилища. Реалистичный подход: при graceful shutdown просто логировать, а middleware (Task 5) обработает потерю при следующем запуске.

- [ ] **Step 1: Добавить комментарий в bot.py**

В блоке `finally` добавить лог:
```python
logger.info("Бот останавливается. Активные FSM-сессии будут сброшены при следующем запуске (FSMGuardMiddleware).")
```

Полноценная отправка сообщений невозможна с `MemoryStorage` — нет API для перечисления активных states. `FSMGuardMiddleware` (Task 5) уже решает эту проблему на стороне клиента.

---

### Task 12: Аудит функционала мастеров

**Files:**
- Проверить: корректность CRUD, FSM, расписание, привязка к записям

- [ ] **Step 1: Проверить CRUD мастеров**

Аудит `handlers/admin_masters.py` + `db/masters.py`:
- Создание: `create_master()` → `seed_master_schedule()` — ок, копирует weekly_schedule
- Чтение: `get_master()`, `get_all_masters()`, `get_active_masters()` — ок
- Обновление: `update_master()` с whitelist полей — ок
- Toggle active: `toggle_master_active()` — ок
- Удаление: **НЕТ** — нет функции удаления мастера. Нужно добавить, если мастер без будущих записей.

- [ ] **Step 2: Добавить удаление мастера**

В `db/masters.py`:
```python
async def delete_master(master_id: int) -> bool:
    """Удалить мастера. Возвращает False если есть будущие записи."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT COUNT(*) FROM appointments
           WHERE master_id = ? AND status = 'scheduled' AND date >= date('now')""",
        (master_id,),
    )
    if (await cursor.fetchone())[0] > 0:
        return False
    await db.execute("DELETE FROM master_schedule WHERE master_id = ?", (master_id,))
    await db.execute("DELETE FROM masters WHERE id = ?", (master_id,))
    await db.commit()
    return True
```

В `handlers/admin_masters.py` — добавить callback:
```python
@router.callback_query(F.data.startswith("master_delete_"))
async def cb_master_delete(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    master_id = int(callback.data.split("_")[2])
    from db import delete_master
    success = await delete_master(master_id)
    if not success:
        await callback.answer("Нельзя удалить: есть будущие записи.", show_alert=True)
        return
    await _show_masters(callback)
    await callback.answer("Мастер удалён.")
```

В `keyboards/inline.py`, в `master_card_keyboard()` — добавить кнопку удаления.

- [ ] **Step 3: Проверить привязку мастера к записям**

Аудит: `create_appointment` принимает `master_id`, сохраняет в БД — ок.
`get_appointments_by_date_full` JOIN с masters — ок.
`get_booked_times` фильтрует по `master_id` — ок.
`is_slot_free` фильтрует по `master_id` — ок.

- [ ] **Step 4: Проверить расписание мастера**

Аудит: `get_day_schedule_for_master` проверяет blocked_slots + master_schedule — ок.
`get_day_off_weekdays_for_master` — ок.
`get_time_blocks_for_master` — включает глобальные блокировки (`master_id IS NULL`) — ок.

- [ ] **Step 5: Проверить FSM при выборе мастера**

Аудит `_show_master_step()`:
- 0 мастеров → пропуск шага, переход к датам без master_id — ок
- 1 мастер → авто-выбор, `state.update_data(master_id=...)` — ок
- \>1 → показ клавиатуры → `choose_master` → `state.update_data(master_id=...)` — ок

**Найденная проблема:** при авто-выборе единственного мастера используются `get_day_off_weekdays_for_master`, но при 0 мастеров — глобальный `_day_off_weekdays()`. Это корректно.

- [ ] **Step 6: Проверить что master_card_keyboard содержит кнопку удаления**

Прочитать `keyboards/inline.py` → `master_card_keyboard()` и добавить кнопку `🗑 Удалить` если её нет.

---

### Task 13: Финальная проверка

- [ ] **Step 1: Проверить все импорты**

Run: `python -c "import bot; print('All imports OK')"`
Expected: ошибки отсутствуют (бот не запустится без .env, но импорты пройдут если BOT_TOKEN задан)

- [ ] **Step 2: Полный lint**

Run: `python -m py_compile bot.py && python -m py_compile handlers/client.py && python -m py_compile handlers/admin.py && echo OK`

- [ ] **Step 3: Проверить запуск бота**

Run: `timeout 5 python bot.py` (с настроенным .env)
Expected: `Бот запущен` в логах, без ошибок импорта.
