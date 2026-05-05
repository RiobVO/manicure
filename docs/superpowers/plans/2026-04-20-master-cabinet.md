# Master Cabinet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить read-only кабинет мастера в существующий бот: мастер с привязанным `user_id` видит свои сегодняшние записи, ближайшие scheduled записи и недельное расписание через три reply-кнопки.

**Architecture:** В `utils/admin.py` появляется симметричный мастерам кеш, фильтр и `is_master()`. В `handlers/master.py` — новый роутер с `IsMasterFilter`, тремя обработчиками reply-кнопок и entry-функцией. В `handlers/client.py::cmd_start` добавляется ветка `elif is_master(...)` между admin и client. В `bot.py` — регистрация роутера между admin и reviews/client. Ноль миграций, ноль новых таблиц, ноль новых зависимостей.

**Tech Stack:** aiogram 3.7, aiosqlite, Python 3.12. Все паттерны уже существуют в проекте (кеш ролей, `edit_panel`, reply-клавиатуры, роутер-фильтры).

**Project convention:** Тесты НЕ пишем (явное правило автора). Финальная верификация — одна ручная команда из секции «Task 8». Один итоговый коммит на всю фазу.

---

## Структура файлов

**Создаваемые:**
- `handlers/master.py` — роутер кабинета мастера, 3 обработчика + entry-функция.

**Изменяемые:**
- `db/masters.py` — +3 функции запросов (существующие не трогаем).
- `db/__init__.py` — экспорт новых функций.
- `utils/admin.py` — `_db_masters_cache`, `refresh_masters_cache`, `is_master`, `IsMasterFilter`.
- `keyboards/inline.py` — `master_reply_keyboard()`.
- `handlers/client.py` — `cmd_start` получает ветку `elif is_master(...)`.
- `handlers/admin_masters.py` — вызовы `refresh_masters_cache()` после всех мутаций мастеров.
- `bot.py` — импорт и регистрация `master.router`, вызов `refresh_masters_cache()` на старте.

---

### Task 1: Добавить DB-запросы в `db/masters.py` и экспортировать

**Files:**
- Modify: `db/masters.py` (append в конец файла)
- Modify: `db/__init__.py:57-70` (секция masters exports)

- [ ] **Step 1: Добавить три функции в конец `db/masters.py`**

```python
async def get_master_by_user_id(user_id: int) -> dict[str, Any] | None:
    """Возвращает активного мастера, привязанного к TG user_id, или None.
    Используется для role-routing и для загрузки данных кабинета."""
    return await _dict_row(
        "SELECT * FROM masters WHERE user_id = ? AND is_active = 1",
        (user_id,),
    )


async def get_active_masters_with_user_id() -> list[dict[str, Any]]:
    """Активные мастера с привязанным user_id — для построения masters-кеша.
    Мастера без user_id в кабинет не попадут и в кеше не нужны."""
    return await _dict_rows(
        "SELECT id, user_id, name FROM masters WHERE is_active = 1 AND user_id IS NOT NULL"
    )


async def get_master_appointments_today(
    master_id: int, date_str: str,
) -> list[dict[str, Any]]:
    """Записи мастера на указанную дату: scheduled + completed + no_show.
    Отменённые (cancelled) исключены — мастеру они не нужны."""
    return await _dict_rows(
        """SELECT id, time, name, phone, service_name, service_duration, status
           FROM appointments
           WHERE master_id = ? AND date = ?
             AND status IN ('scheduled', 'completed', 'no_show')
           ORDER BY time""",
        (master_id, date_str),
    )


async def get_master_appointments_upcoming(
    master_id: int, from_date: str, limit: int = 30,
) -> list[dict[str, Any]]:
    """Scheduled записи мастера от даты (включительно), ORDER BY date, time.
    Лимит 30 — чтобы экран не превращался в простыню; при переполнении
    показываем хвост «... и ещё N» на UI-слое."""
    return await _dict_rows(
        """SELECT id, date, time, name, phone, service_name, service_duration
           FROM appointments
           WHERE master_id = ? AND status = 'scheduled' AND date >= ?
           ORDER BY date, time
           LIMIT ?""",
        (master_id, from_date, limit),
    )
```

- [ ] **Step 2: Экспортировать новые функции в `db/__init__.py`**

Найти блок `from db.masters import (` (строка 57). Добавить в список импортов, в алфавитном порядке по смыслу (после `get_master`):

```python
from db.masters import (
    get_active_masters,
    get_all_masters,
    get_master,
    get_master_by_user_id,                  # NEW
    get_active_masters_with_user_id,        # NEW
    get_master_appointments_today,          # NEW
    get_master_appointments_upcoming,       # NEW
    create_master,
    update_master,
    toggle_master_active,
    delete_master,
    seed_master_schedule,
    get_master_schedule,
    get_day_schedule_for_master,
    get_day_off_weekdays_for_master,
    get_time_blocks_for_master,
)
```

---

### Task 2: Masters-кеш, `is_master`, `IsMasterFilter` в `utils/admin.py`

**Files:**
- Modify: `utils/admin.py` (append блок после существующего `IsAdminFilter`)

- [ ] **Step 1: Добавить masters-инфраструктуру в конец `utils/admin.py`**

```python
# ─── Masters: cache + filter ─────────────────────────────────────────────────
# Параллельная инфраструктура ADMIN-кешу: множество user_id активных мастеров
# с привязанным TG-id. Мастера без user_id в кеш не попадают — им кабинет
# недоступен, пока админ не привяжет TG.

_db_masters_cache: set[int] = set()


async def refresh_masters_cache() -> None:
    """Обновить кеш user_id активных мастеров. Вызывается на старте бота
    и после любой мутации masters (create/update user_id/toggle/delete)."""
    global _db_masters_cache
    from db import get_active_masters_with_user_id
    rows = await get_active_masters_with_user_id()
    _db_masters_cache = {r["user_id"] for r in rows}


def is_master(user_id: int) -> bool:
    """True если user_id привязан к активному мастеру."""
    return user_id in _db_masters_cache


class IsMasterFilter(BaseFilter):
    """Фильтр роутер-уровня: пропускает только мастеров (не-админов-мастеров тоже)."""

    async def __call__(self, event: TelegramObject) -> bool:
        user = getattr(event, "from_user", None)
        if user is None:
            return False
        return is_master(user.id)
```

---

### Task 3: `master_reply_keyboard()` в `keyboards/inline.py`

**Files:**
- Modify: `keyboards/inline.py` (вставить после существующего `admin_reply_keyboard`, строка ~351)

- [ ] **Step 1: Добавить функцию сразу после `admin_reply_keyboard`**

```python
def master_reply_keyboard() -> ReplyKeyboardMarkup:
    """Постоянная нижняя клавиатура мастера (кабинет мастера).
    Текст '📋 Сегодня' совпадает с админским — разрулено на уровне
    router-filter: admin-router IsAdminFilter, master-router IsMasterFilter."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Сегодня")],
            [KeyboardButton(text="📅 Мои записи")],
            [KeyboardButton(text="📆 Моё расписание")],
        ],
        resize_keyboard=True,
    )
```

---

### Task 4: Создать `handlers/master.py` — роутер кабинета

**Files:**
- Create: `handlers/master.py`

- [ ] **Step 1: Создать файл со всем содержимым**

```python
"""
Кабинет мастера: read-only pull-интерфейс для мастера в том же боте.

Попадание сюда означает, что user_id привязан к активному мастеру.
Role-routing происходит в handlers/client.py::cmd_start (elif is_master),
entry-функция ниже вызывается оттуда.

Никакого FSM. Три reply-кнопки — 'Сегодня', 'Мои записи', 'Расписание'.
Все три пишут через edit_panel в единое сообщение-панель (как админка).
"""
import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from constants import MONTHS_RU, WEEKDAYS_FULL_RU, WEEKDAYS_SHORT_RU
from db import (
    get_master_appointments_today,
    get_master_appointments_upcoming,
    get_master_by_user_id,
    get_master_schedule,
)
from keyboards.inline import master_reply_keyboard
from utils.admin import IsMasterFilter
from utils.panel import (
    clear_panel_msg_id,
    get_panel_lock,
    get_panel_msg_id,
    set_panel_msg_id,
    set_reply_kb,
)
from utils.timezone import now_local

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(IsMasterFilter())
router.callback_query.filter(IsMasterFilter())

_STATUS_ICON = {"scheduled": "🕐", "completed": "✅", "no_show": "🚫"}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _date_human(date_str: str) -> str:
    """YYYY-MM-DD → '20 апреля, пн'."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.day} {MONTHS_RU[dt.month - 1]}, {WEEKDAYS_SHORT_RU[dt.weekday()]}"
    except ValueError:
        return date_str


def _duration_str(minutes: int) -> str:
    """60 → '1ч', 90 → '1ч 30м', 45 → '45м'."""
    if minutes < 60:
        return f"{minutes}м"
    h, m = divmod(minutes, 60)
    return f"{h}ч" if m == 0 else f"{h}ч {m}м"


async def _nav(message: Message, text: str, parse_mode: str | None = None) -> None:
    """
    Удалить сообщение-тап (текст кнопки), отредактировать панель мастера или
    создать новую. Паттерн скопирован из handlers/admin.py::_nav,
    но без inline-markup (мастер не нажимает кнопок — read-only).
    """
    chat_id = message.chat.id
    lock = get_panel_lock(chat_id)
    async with lock:
        try:
            await message.delete()
        except Exception:
            pass  # уже удалено или нет прав — не блокируем навигацию

        nav_id = get_panel_msg_id(chat_id)
        if nav_id:
            try:
                await message.bot.edit_message_text(
                    text, chat_id=chat_id, message_id=nav_id,
                    parse_mode=parse_mode,
                )
                return
            except TelegramBadRequest:
                try:
                    await message.bot.delete_message(chat_id, nav_id)
                except Exception:
                    pass
                clear_panel_msg_id(chat_id)

        sent = await message.bot.send_message(chat_id, text, parse_mode=parse_mode)
        set_panel_msg_id(chat_id, sent.message_id)


# ─── Entry (вызывается из client.py::cmd_start) ──────────────────────────────

async def show_master_cabinet_entry(message: Message, state: FSMContext) -> None:
    """
    Встречает мастера после /start: ставит reply-клавиатуру и показывает
    приветствие с именем. Вызывается из client.py::cmd_start при is_master.
    """
    await state.clear()
    master = await get_master_by_user_id(message.from_user.id)
    if master is None:
        # Гонка: между IsMasterFilter и этим вызовом мастер был деактивирован.
        # Тихо выходим — пусть следующий /start попадёт в клиентский флоу.
        return

    # Удаляем само /start-сообщение, чтобы чат не засорялся
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    set_reply_kb(message.chat.id, master_reply_keyboard())
    await message.answer(
        f"👨\u200d🎨 <b>Кабинет мастера</b>\n"
        f"<i>{master['name']}</i>\n\n"
        f"Выбери что посмотреть ↓",
        reply_markup=master_reply_keyboard(),
        parse_mode="HTML",
    )


# ─── Reply buttons ───────────────────────────────────────────────────────────

@router.message(StateFilter("*"), F.text == "📋 Сегодня")
async def msg_today(message: Message, state: FSMContext) -> None:
    """Сегодняшние записи: scheduled + completed + no_show. Без cancelled."""
    await state.clear()
    master = await get_master_by_user_id(message.from_user.id)
    if master is None:
        return

    date_str = now_local().strftime("%Y-%m-%d")
    appointments = await get_master_appointments_today(master["id"], date_str)

    if not appointments:
        await _nav(
            message,
            f"📋 <b>Сегодня, {_date_human(date_str)}</b>\n\n"
            f"<i>Записей нет. Хорошего дня.</i>",
            parse_mode="HTML",
        )
        return

    lines = [f"📋 <b>Сегодня, {_date_human(date_str)}</b>"]
    for a in appointments:
        icon = _STATUS_ICON.get(a["status"], "·")
        lines.append(
            f"\n{icon} <b>{a['time']}</b> — {a['name']}\n"
            f"   💅 {a['service_name']} ({_duration_str(a['service_duration'])})\n"
            f"   📞 {a['phone']}"
        )

    await _nav(message, "\n".join(lines), parse_mode="HTML")


@router.message(StateFilter("*"), F.text == "📅 Мои записи")
async def msg_upcoming(message: Message, state: FSMContext) -> None:
    """Ближайшие scheduled на сегодня и вперёд, до 30 штук, группировка по дате."""
    await state.clear()
    master = await get_master_by_user_id(message.from_user.id)
    if master is None:
        return

    today = now_local().strftime("%Y-%m-%d")
    appointments = await get_master_appointments_upcoming(master["id"], today, limit=30)

    if not appointments:
        await _nav(
            message,
            "📅 <b>Твои ближайшие записи</b>\n\n<i>Пока ничего запланировано.</i>",
            parse_mode="HTML",
        )
        return

    lines = ["📅 <b>Твои ближайшие записи</b>"]
    current_date = None
    for a in appointments:
        if a["date"] != current_date:
            current_date = a["date"]
            lines.append(f"\n<b>—— {_date_human(current_date)} ——</b>")
        lines.append(
            f"🕐 <b>{a['time']}</b> — {a['name']} · {a['service_name']} · 📞 {a['phone']}"
        )

    if len(appointments) == 30:
        lines.append("\n<i>... показаны первые 30. Остальные — позже.</i>")

    await _nav(message, "\n".join(lines), parse_mode="HTML")


@router.message(StateFilter("*"), F.text == "📆 Моё расписание")
async def msg_schedule(message: Message, state: FSMContext) -> None:
    """Недельная сетка из master_schedule. Пустые weekdays / work_start=None → выходной."""
    await state.clear()
    master = await get_master_by_user_id(message.from_user.id)
    if master is None:
        return

    schedule = await get_master_schedule(master["id"])

    lines = ["📆 <b>Твоё расписание</b>\n"]
    for weekday in range(7):
        row = schedule.get(weekday)
        day_name = WEEKDAYS_FULL_RU[weekday]
        if row is None or row["work_start"] is None:
            lines.append(f"<b>{day_name}</b> — <i>выходной</i>")
        else:
            lines.append(
                f"<b>{day_name}</b>  <code>{row['work_start']:02d}:00 – {row['work_end']:02d}:00</code>"
            )
    lines.append("\n<i>Изменить расписание — через администратора.</i>")

    await _nav(message, "\n".join(lines), parse_mode="HTML")
```

---

### Task 5: Регистрация роутера в `bot.py` + refresh_masters_cache на старте

**Files:**
- Modify: `bot.py:27-31` (блок импортов хендлеров)
- Modify: `bot.py:34` (импорт refresh_admins_cache)
- Modify: `bot.py:143-149` (регистрация поздних роутеров)
- Modify: `bot.py:151-152` (init_db + refresh на старте)

- [ ] **Step 1: Импорт модуля мастера**

Найти блок (строки 27-31):
```python
from handlers import client, admin
from handlers import admin_appointments, admin_clients, admin_services
from handlers import admin_stats, admin_settings, admin_blocks, admin_manage
from handlers import reviews, admin_export, admin_masters
from handlers import client_reminders, client_history, admin_status
```

Заменить на (добавлена одна строка с `master`):
```python
from handlers import client, admin
from handlers import admin_appointments, admin_clients, admin_services
from handlers import admin_stats, admin_settings, admin_blocks, admin_manage
from handlers import reviews, admin_export, admin_masters
from handlers import client_reminders, client_history, admin_status
from handlers import master
```

- [ ] **Step 2: Импорт refresh_masters_cache**

Найти (строка 34):
```python
from utils.admin import refresh_admins_cache
```

Заменить на:
```python
from utils.admin import refresh_admins_cache, refresh_masters_cache
```

- [ ] **Step 3: Вставить регистрацию master.router между admin-блоком и reviews**

Найти блок регистрации роутеров (строки 143-149):
```python
    dp.include_router(reviews.router)  # до client.router — чтобы rev_* callbacks не попали в fallback
    # client_reminders и client_history — ДО client.router, т.к. client содержит
    # catch-all fallback_message. Порядок внутри этой тройки неважен (у них нет пересечений),
    # кроме того, что конкретные F-фильтры должны предшествовать catch-all message().
    dp.include_router(client_reminders.router)
    dp.include_router(client_history.router)
    dp.include_router(client.router)
```

Заменить на (добавить master.router первой строкой блока):
```python
    # master.router — ПОСЛЕ всех admin-роутеров, но ДО reviews/client_reminders/client_history/client:
    # IsMasterFilter поймает только активных мастеров с user_id, остальные провалятся дальше.
    dp.include_router(master.router)
    dp.include_router(reviews.router)  # до client.router — чтобы rev_* callbacks не попали в fallback
    # client_reminders и client_history — ДО client.router, т.к. client содержит
    # catch-all fallback_message. Порядок внутри этой тройки неважен (у них нет пересечений),
    # кроме того, что конкретные F-фильтры должны предшествовать catch-all message().
    dp.include_router(client_reminders.router)
    dp.include_router(client_history.router)
    dp.include_router(client.router)
```

- [ ] **Step 4: Вызвать refresh_masters_cache() на старте**

Найти (строки 151-152):
```python
    await init_db()
    await refresh_admins_cache()
```

Заменить на:
```python
    await init_db()
    await refresh_admins_cache()
    await refresh_masters_cache()
```

---

### Task 6: Добавить ветку `elif is_master(...)` в `cmd_start`

**Files:**
- Modify: `handlers/client.py:45` (импорт `ADMIN_IDS`) — добавить `is_master`
- Modify: `handlers/client.py:196-258` (тело `cmd_start`)

- [ ] **Step 1: Импортировать `is_master` в client.py**

Найти (строка 45):
```python
from config import ADMIN_IDS
```

Оставить как есть. Добавить НОВУЮ строку сразу после:
```python
from config import ADMIN_IDS
from utils.admin import is_master
```

(Если `from utils.admin import ...` уже есть в файле — объединить с существующим импортом. Беглым чтением подтверждено: `utils.admin` импортируется только в `set_reply_kb` из `utils.panel`, отдельного импорта из `utils.admin` в client.py сейчас нет, так что добавляем новой строкой.)

- [ ] **Step 2: Добавить ветку мастера в `cmd_start`**

Найти тело `cmd_start` (строки 196-258), конкретно:
```python
@router.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()

    if message.from_user.id in ADMIN_IDS:
        try:
            await message.delete()
        except TelegramBadRequest:
            pass  # сообщение уже удалено или недоступно
        # Сохраняем reply keyboard для этого чата
        set_reply_kb(message.chat.id, admin_reply_keyboard())
        # Отправляем ТОЛЬКО reply keyboard — без дополнительного сообщения
        await message.answer("👑 <b>Панель мастера</b>", reply_markup=admin_reply_keyboard(), parse_mode="HTML")
        return

    # Показать reply-клавиатуру тихо (невидимый разделитель — иначе сообщение нельзя отправить)
    await message.answer("\u2063", reply_markup=client_reply_keyboard())
    ...
```

Вставить ветку мастера СРАЗУ ПОСЛЕ `return` админской ветки и ДО строки `# Показать reply-клавиатуру тихо...`:

```python
    if message.from_user.id in ADMIN_IDS:
        try:
            await message.delete()
        except TelegramBadRequest:
            pass  # сообщение уже удалено или недоступно
        # Сохраняем reply keyboard для этого чата
        set_reply_kb(message.chat.id, admin_reply_keyboard())
        # Отправляем ТОЛЬКО reply keyboard — без дополнительного сообщения
        await message.answer("👑 <b>Панель мастера</b>", reply_markup=admin_reply_keyboard(), parse_mode="HTML")
        return

    # Мастер (user_id привязан к активной записи в masters) — свой кабинет.
    # Late import handlers.master, чтобы избежать потенциального circular import
    # на уровне модуля (client.py грузится при импорте хендлеров в bot.py).
    if is_master(message.from_user.id):
        from handlers.master import show_master_cabinet_entry
        await show_master_cabinet_entry(message, state)
        return

    # Показать reply-клавиатуру тихо (невидимый разделитель — иначе сообщение нельзя отправить)
    await message.answer("\u2063", reply_markup=client_reply_keyboard())
```

**Замечание:** Админские `ADMIN_IDS` не дополняем `_db_admins_cache` здесь — существующее поведение сохраняем (admin-handlers пользуются `is_admin()` из `utils.admin` через `IsAdminFilter`). Если админ-из-БД пишет `/start`, он попадёт в «новый клиент» флоу так же, как было раньше. Это не регрессия — уже так работало. Исправление вне scope этой фазы.

---

### Task 7: Вызовы `refresh_masters_cache()` в `handlers/admin_masters.py` после мутаций

**Files:**
- Modify: `handlers/admin_masters.py` (5 мест: toggle, delete, create-final, edit-name/user_id/bio)

- [ ] **Step 1: Импортировать `refresh_masters_cache`**

В секции импортов `handlers/admin_masters.py` (строки 14-17) найти:
```python
from utils.admin import is_admin_callback, is_admin_message, deny_access, IsAdminFilter
```

Заменить на:
```python
from utils.admin import is_admin_callback, is_admin_message, deny_access, IsAdminFilter, refresh_masters_cache
```

- [ ] **Step 2: Вызов после `toggle_master_active`**

Найти `cb_master_toggle` (строка 74), внутри:
```python
    master_id = int(parts[0])
    await toggle_master_active(master_id)
    await cb_master_card(callback)
```

Заменить на:
```python
    master_id = int(parts[0])
    await toggle_master_active(master_id)
    await refresh_masters_cache()
    await cb_master_card(callback)
```

- [ ] **Step 3: Вызов после `delete_master`**

Найти `cb_master_delete` (строка 91), внутри:
```python
    success = await delete_master(master_id)
    if not success:
        await callback.answer(
            "Нельзя удалить: у мастера есть история записей. Можно деактивировать.",
            show_alert=True,
        )
        return
    await _show_masters(callback)
    await callback.answer("Мастер удалён.")
```

Заменить на:
```python
    success = await delete_master(master_id)
    if not success:
        await callback.answer(
            "Нельзя удалить: у мастера есть история записей. Можно деактивировать.",
            show_alert=True,
        )
        return
    await refresh_masters_cache()
    await _show_masters(callback)
    await callback.answer("Мастер удалён.")
```

- [ ] **Step 4: Вызов после `create_master` (конец create-flow)**

Найти `msg_master_add_bio` (строка 179), внутри:
```python
    master_id = await create_master(
        user_id=data.get("master_user_id"),
        name=data["master_name"],
        bio=bio,
    )
    await state.clear()
```

Заменить на:
```python
    master_id = await create_master(
        user_id=data.get("master_user_id"),
        name=data["master_name"],
        bio=bio,
    )
    await refresh_masters_cache()
    await state.clear()
```

- [ ] **Step 5: Вызов после `update_master(user_id=...)` (edit user_id)**

Найти `msg_master_edit_user_id` (строка 277), внутри:
```python
    data = await state.get_data()
    master_id = data["edit_master_id"]
    await update_master(master_id, user_id=user_id)
    await state.clear()
```

Заменить на:
```python
    data = await state.get_data()
    master_id = data["edit_master_id"]
    await update_master(master_id, user_id=user_id)
    await refresh_masters_cache()
    await state.clear()
```

- [ ] **Step 6: Имя и bio — NOT triggering cache refresh**

`msg_master_edit_name` и `msg_master_edit_bio` меняют поля, которые не влияют на кеш (`name`, `bio`). Не добавляем `refresh_masters_cache()` — это экономит лишний SELECT при невзрывоопасных правках.

Убедиться, что в `msg_master_edit_name` (строка 230) и `msg_master_edit_bio` (строка 322) вызова `refresh_masters_cache()` **нет** и он не появляется.

---

### Task 8: Ручная верификация

**Files:** ничего не создаём. Тестирует автор в своей среде.

- [ ] **Step 1: Пересобрать и запустить**

В docker (продакшн-стиль автора):
```bash
docker compose up -d --build
docker compose logs -f bot
```

Ожидаемо в логах:
- `License mode=...`
- `Бот запущен`
- Отсутствие ERROR / Traceback на старте.

- [ ] **Step 2: Сценарий — базовый (мастер видит кабинет)**

Pre-условия: у автора есть второй тестовый TG-аккаунт (назовём его **B**), `user_id` аккаунта B известен. Аккаунт автора — **A** — уже в `ADMIN_IDS`.

1. С аккаунта **A** (админ): открыть бот, «👨‍🎨 Мастера» → «➕ Добавить мастера». Имя — «Тест Мастер». `user_id` — ID аккаунта **B**. Bio — `/skip`.
2. С аккаунта **B**: написать боту `/start`.
3. **Ожидаемо:** появляется сообщение «👨‍🎨 Кабинет мастера / Тест Мастер / Выбери что посмотреть ↓» и reply-клавиатура с тремя кнопками: «📋 Сегодня», «📅 Мои записи», «📆 Моё расписание».
4. **Не должно:** появиться клиентское меню «ручки или ножки?» или админская клавиатура со «Статистика / Настройки / ...».

- [ ] **Step 3: Сценарий — «Сегодня» с пустым и заполненным списком**

1. С **B** нажать «📋 Сегодня» → ожидаемо «Записей нет. Хорошего дня.» (пока записей нет).
2. С **A** (админ) создать запись для мастера «Тест Мастер» на сегодня — любой валидный способ (через клиента или перенос существующей). Самый простой: с третьего тестового TG-аккаунта **C** забронировать на сегодня к «Тест Мастер».
3. С **B** нажать «📋 Сегодня» → ожидаемо увидеть строку вида:
   ```
   🕐 HH:MM — <имя клиента>
      💅 <услуга> (длительность)
      📞 <телефон>
   ```

- [ ] **Step 4: Сценарий — «Мои записи» и «Расписание»**

1. С **B** нажать «📅 Мои записи» → сегодняшняя запись из Step 3 должна появиться под заголовком `—— <дата>, <день> ——`.
2. С **B** нажать «📆 Моё расписание» → должна появиться недельная сетка Пн-Вс с часами работы из `master_schedule` (при seed-дефолтах: 09:00–19:00 для всех 7 дней).

- [ ] **Step 5: Сценарий — деактивация в процессе**

1. С **A**: «Мастера» → «Тест Мастер» → «🔴/🟢 ...» (toggle) — деактивировать.
2. С **B** написать `/start`.
3. **Ожидаемо:** попадает в клиентский флоу («ручки или ножки?»), НЕ в кабинет.
4. С **A** активировать обратно — с **B** `/start` снова в кабинет.

- [ ] **Step 6: Сценарий — admin > master (приоритет)**

1. С **A** (этот же аккаунт — админ): «Мастера» → создать мастера «Автор-Мастер» с `user_id = A.id`.
2. С **A** написать `/start`.
3. **Ожидаемо:** открывается админская панель (👑), НЕ кабинет мастера. Админ имеет приоритет.
4. Cleanup: удалить тестового мастера «Автор-Мастер» из админ-панели.

- [ ] **Step 7: Коммит (одна финальная фаза)**

Если все 6 сценариев прошли — один коммит:

```bash
git add db/masters.py db/__init__.py utils/admin.py keyboards/inline.py \
        handlers/master.py handlers/client.py handlers/admin_masters.py \
        bot.py
git commit -m "feat(master): read-only cabinet — today/upcoming/schedule via role routing"
```

Если какой-либо сценарий упал — **не** коммитить, использовать `debug-context` скилл, фиксить, перепроверять только упавший сценарий, потом коммит.
