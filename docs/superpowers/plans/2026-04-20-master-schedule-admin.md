# Master Schedule Admin Editor — Implementation Plan (Phase 2 v.2)

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать админу UI для редактирования персонального расписания мастера (`master_schedule` per-master) — toggle выходной, edit start/end час для каждого weekday. Зеркало существующего UI редактирования салонно-глобального графика в `handlers/admin_settings.py`, но с фильтром по `master_id`.

**Architecture:** Новый файл `handlers/admin_master_schedule.py` с изолированным роутером. Callback-namespace `master_sched_*` / `msched_*`. Upsert в `master_schedule` через новую функцию `update_master_weekday`. Мастер в своём кабинете остаётся read-only — не меняется.

**Tech Stack:** aiogram 3.7, aiosqlite. Все паттерны существуют в проекте (см. `admin_settings.py` как образец).

**Project convention:** Тесты НЕ пишем (правило автора). Один финальный коммит после ручной верификации.

---

## Структура файлов

**Создаваемые:**
- `handlers/admin_master_schedule.py` — роутер админа для редактирования per-master расписания.

**Изменяемые:**
- `db/masters.py` — +`update_master_weekday(master_id, weekday, work_start, work_end)`.
- `db/__init__.py` — экспорт новой функции.
- `states.py` — +2 FSM states (`master_schedule_edit_start`, `master_schedule_edit_end`).
- `keyboards/inline.py` — +`master_weekly_schedule_keyboard`, +`master_weekday_detail_keyboard`, + кнопка «📆 Расписание» в `master_card_keyboard`.
- `bot.py` — импорт + `include_router(admin_master_schedule.router)` после `admin_masters.router`.

---

### Task A: DB — `update_master_weekday` + экспорт

**Files:**
- Modify: `db/masters.py` (append в конец)
- Modify: `db/__init__.py:56-74` (блок masters)

- [ ] **Step 1: Добавить функцию в `db/masters.py`**

```python
async def update_master_weekday(
    master_id: int,
    weekday: int,
    work_start: int | None,
    work_end: int | None,
) -> None:
    """Upsert строки master_schedule для мастера и дня недели.

    work_start=None, work_end=None → день помечен выходным.
    Используется админским редактором расписания. Мастер права на это не имеет."""
    db = await get_db()
    await db.execute(
        """INSERT INTO master_schedule (master_id, weekday, work_start, work_end)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(master_id, weekday) DO UPDATE SET
               work_start = excluded.work_start,
               work_end   = excluded.work_end""",
        (master_id, weekday, work_start, work_end),
    )
    await db.commit()
```

- [ ] **Step 2: Экспорт в `db/__init__.py`**

В блоке `from db.masters import (...)` добавить `update_master_weekday` сразу после `get_day_off_weekdays_for_master`:

```python
from db.masters import (
    get_active_masters,
    get_all_masters,
    get_master,
    get_master_by_user_id,
    get_active_masters_with_user_id,
    get_master_appointments_today,
    get_master_appointments_upcoming,
    create_master,
    update_master,
    toggle_master_active,
    delete_master,
    seed_master_schedule,
    get_master_schedule,
    get_day_schedule_for_master,
    get_day_off_weekdays_for_master,
    update_master_weekday,                      # NEW
    get_time_blocks_for_master,
)
```

---

### Task B: FSM states — 2 новых

**Files:**
- Modify: `states.py`

- [ ] **Step 1: Добавить два атрибута в класс `AdminStates`**

Открой `states.py`. Найди класс `AdminStates`. В нём уже есть состояния `schedule_edit_start`, `schedule_edit_end` (для глобального). Рядом добавь два новых:

```python
    master_schedule_edit_start = State()
    master_schedule_edit_end   = State()
```

Если в классе уже есть эти имена под другим названием — переиспользовать НЕЛЬЗЯ, callbacks у них разные (prefix разный).

---

### Task C: Клавиатуры — 2 новых + кнопка на карточке мастера

**Files:**
- Modify: `keyboards/inline.py`

- [ ] **Step 1: Добавить `master_weekly_schedule_keyboard`**

Найди в файле функцию `weekly_schedule_keyboard` (зеркалим её). Рядом с ней добавь:

```python
def master_weekly_schedule_keyboard(
    master_id: int,
    schedule: dict[int, dict],
) -> InlineKeyboardMarkup:
    """Недельная сетка per-master: 7 кнопок по дням + '🔙 К мастеру'.
    schedule: {weekday: {'work_start': int|None, 'work_end': int|None}}.
    Отсутствующий weekday или work_start=None → выходной."""
    from constants import WEEKDAYS_SHORT_RU
    buttons = []
    for wd in range(7):
        row = schedule.get(wd) or {}
        if row.get("work_start") is None:
            label = f"{WEEKDAYS_SHORT_RU[wd]} — выходной"
        else:
            label = f"{WEEKDAYS_SHORT_RU[wd]} {row['work_start']:02d}:00–{row['work_end']:02d}:00"
        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"msched_day_{master_id}_{wd}",
        )])
    buttons.append([InlineKeyboardButton(
        text="🔙 К мастеру",
        callback_data=f"master_card_{master_id}",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
```

- [ ] **Step 2: Добавить `master_weekday_detail_keyboard`**

Сразу под предыдущей функцией:

```python
def master_weekday_detail_keyboard(
    master_id: int,
    weekday: int,
    is_day_off: bool,
) -> InlineKeyboardMarkup:
    """Детали weekday для мастера: toggle / edit start / edit end / back."""
    toggle_text = "🟢 Сделать рабочим" if is_day_off else "🔴 Сделать выходным"
    buttons = [
        [InlineKeyboardButton(
            text=toggle_text,
            callback_data=f"msched_toggle_{master_id}_{weekday}",
        )],
    ]
    if not is_day_off:
        buttons.append([
            InlineKeyboardButton(
                text="🕐 Час начала",
                callback_data=f"msched_edit_start_{master_id}_{weekday}",
            ),
            InlineKeyboardButton(
                text="🕕 Час конца",
                callback_data=f"msched_edit_end_{master_id}_{weekday}",
            ),
        ])
    buttons.append([InlineKeyboardButton(
        text="🔙 К расписанию",
        callback_data=f"master_sched_{master_id}",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
```

- [ ] **Step 3: Добавить кнопку «📆 Расписание» в `master_card_keyboard`**

Найди функцию `master_card_keyboard` (около строки 262). Сейчас она выглядит так:

```python
def master_card_keyboard(master_id: int, is_active: bool) -> InlineKeyboardMarkup:
    toggle_text = "🔴 Деактивировать" if is_active else "🟢 Активировать"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Имя",    callback_data=f"master_edit_name_{master_id}"),
            InlineKeyboardButton(text="🆔 User ID", callback_data=f"master_edit_uid_{master_id}"),
        ],
        [InlineKeyboardButton(text="📝 Описание",  callback_data=f"master_edit_bio_{master_id}")],
        [InlineKeyboardButton(text=toggle_text,     callback_data=f"master_toggle_{master_id}")],
        [InlineKeyboardButton(text="🗑 Удалить",    callback_data=f"master_delete_{master_id}")],
        [InlineKeyboardButton(text="🔙 К мастерам", callback_data="admin_masters")],
    ])
```

Добавь строку с кнопкой «📆 Расписание» между «📝 Описание» и «toggle_text»:

```python
def master_card_keyboard(master_id: int, is_active: bool) -> InlineKeyboardMarkup:
    toggle_text = "🔴 Деактивировать" if is_active else "🟢 Активировать"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Имя",    callback_data=f"master_edit_name_{master_id}"),
            InlineKeyboardButton(text="🆔 User ID", callback_data=f"master_edit_uid_{master_id}"),
        ],
        [InlineKeyboardButton(text="📝 Описание",  callback_data=f"master_edit_bio_{master_id}")],
        [InlineKeyboardButton(text="📆 Расписание", callback_data=f"master_sched_{master_id}")],
        [InlineKeyboardButton(text=toggle_text,     callback_data=f"master_toggle_{master_id}")],
        [InlineKeyboardButton(text="🗑 Удалить",    callback_data=f"master_delete_{master_id}")],
        [InlineKeyboardButton(text="🔙 К мастерам", callback_data="admin_masters")],
    ])
```

---

### Task D: Admin UI — `handlers/admin_master_schedule.py`

**Files:**
- Create: `handlers/admin_master_schedule.py`

- [ ] **Step 1: Создать файл**

```python
"""
Админский редактор per-master расписания.

Зеркало handlers/admin_settings.py (редактор глобального weekly_schedule),
но фильтрует по конкретному master_id. Мастер редактировать не может —
этот роутер за IsAdminFilter.

Callback-namespace:
  master_sched_<id>                — открыть недельную сетку мастера
  msched_day_<id>_<weekday>        — детализация weekday
  msched_toggle_<id>_<weekday>     — toggle выходной
  msched_edit_start_<id>_<weekday> — FSM на редактирование часа начала
  msched_edit_end_<id>_<weekday>   — FSM на редактирование часа конца
"""
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from constants import WEEKDAYS_FULL_RU
from db import (
    get_master,
    get_master_schedule,
    update_master_weekday,
)
from db.connection import get_db
from keyboards.inline import (
    admin_cancel_keyboard,
    master_weekday_detail_keyboard,
    master_weekly_schedule_keyboard,
)
from states import AdminStates
from utils.admin import (
    IsAdminFilter,
    deny_access,
    is_admin_callback,
    is_admin_message,
)
from utils.callbacks import parse_callback
from utils.panel import edit_panel, edit_panel_with_callback

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(IsAdminFilter())
router.callback_query.filter(IsAdminFilter())


async def _count_master_schedule_conflicts(
    master_id: int,
    weekday: int,
    new_work_start: int,
    new_work_end: int,
) -> int:
    """Количество будущих scheduled записей мастера на указанный weekday,
    выходящих за новые часы работы. Паттерн из admin_settings.py."""
    # SQLite %w: Sun=0..Sat=6. Python Mon=0..Sun=6. Сдвиг +1 mod 7.
    sqlite_wd = str((weekday + 1) % 7)
    db = await get_db()
    cursor = await db.execute(
        """SELECT COUNT(*) FROM appointments
           WHERE master_id = ?
             AND status = 'scheduled'
             AND date >= date('now')
             AND strftime('%w', date) = ?
             AND (
                 CAST(substr(time, 1, 2) AS INTEGER) < ?
                 OR (CAST(substr(time, 1, 2) AS INTEGER) * 60
                     + CAST(substr(time, 4, 2) AS INTEGER)
                     + service_duration) > ? * 60
             )""",
        (master_id, sqlite_wd, new_work_start, new_work_end),
    )
    return (await cursor.fetchone())[0]


async def _show_master_weekly(callback: CallbackQuery, master_id: int) -> None:
    """Показать недельную сетку мастера в панели."""
    master = await get_master(master_id)
    if not master:
        await callback.answer("Мастер не найден.", show_alert=True)
        return
    schedule = await get_master_schedule(master_id)
    text = f"📆 <b>Расписание: {master['name']}</b>\n\nВыбери день для редактирования:"
    await edit_panel_with_callback(
        callback, text,
        master_weekly_schedule_keyboard(master_id, schedule),
        parse_mode="HTML",
    )


# ─── Открыть расписание мастера ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("master_sched_"))
async def cb_master_sched(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "master_sched", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    master_id = int(parts[0])
    await _show_master_weekly(callback, master_id)
    await callback.answer()


# ─── Детализация weekday ─────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("msched_day_"))
async def cb_msched_day(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "msched_day", 2)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    master_id, weekday = int(parts[0]), int(parts[1])

    schedule = await get_master_schedule(master_id)
    row = schedule.get(weekday) or {}
    is_day_off = row.get("work_start") is None
    day_name = WEEKDAYS_FULL_RU[weekday]

    if is_day_off:
        text = f"📅 {day_name} — выходной"
    else:
        text = f"📅 {day_name}  {row['work_start']:02d}:00 – {row['work_end']:02d}:00"

    await edit_panel_with_callback(
        callback, text,
        master_weekday_detail_keyboard(master_id, weekday, is_day_off),
    )
    await callback.answer()


# ─── Toggle выходной ─────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("msched_toggle_"))
async def cb_msched_toggle(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "msched_toggle", 2)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    master_id, weekday = int(parts[0]), int(parts[1])

    schedule = await get_master_schedule(master_id)
    row = schedule.get(weekday) or {}
    is_day_off = row.get("work_start") is None

    if is_day_off:
        # Возвращаем в рабочий день со стандартными часами 9-19.
        await update_master_weekday(master_id, weekday, 9, 19)
    else:
        await update_master_weekday(master_id, weekday, None, None)

    await _show_master_weekly(callback, master_id)
    await callback.answer()


# ─── Редактирование часа начала ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("msched_edit_start_"))
async def cb_msched_edit_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "msched_edit_start", 2)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    master_id, weekday = int(parts[0]), int(parts[1])
    await state.update_data(msched_master_id=master_id, msched_weekday=weekday)
    await edit_panel_with_callback(
        callback,
        "🕐 Введите час начала работы (0–22):",
        admin_cancel_keyboard(),
    )
    await state.set_state(AdminStates.master_schedule_edit_start)
    await callback.answer()


@router.message(AdminStates.master_schedule_edit_start)
async def msg_msched_edit_start(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass
    try:
        value = int(message.text.strip())
        if not (0 <= value <= 22):
            raise ValueError
    except (ValueError, AttributeError):
        await edit_panel(
            message.bot, message.chat.id,
            "⚠️ Введите целое число от 0 до 22:",
            admin_cancel_keyboard(),
        )
        return

    data = await state.get_data()
    master_id = data["msched_master_id"]
    weekday = data["msched_weekday"]

    schedule = await get_master_schedule(master_id)
    row = schedule.get(weekday) or {}
    work_end = row.get("work_end") or 19

    if value >= work_end:
        await edit_panel(
            message.bot, message.chat.id,
            f"⚠️ Начало должно быть меньше конца ({work_end:02d}:00):",
            admin_cancel_keyboard(),
        )
        return

    conflicts = await _count_master_schedule_conflicts(master_id, weekday, value, work_end)
    await update_master_weekday(master_id, weekday, value, work_end)
    await state.clear()

    master = await get_master(master_id)
    schedule = await get_master_schedule(master_id)
    text = f"📆 <b>Расписание: {master['name']}</b>\n\nВыбери день для редактирования:"
    parse_mode = "HTML"
    if conflicts > 0:
        text = (
            f"⚠️ <b>Внимание:</b> есть {conflicts} запись/записей вне новых часов работы. "
            "Проверьте «Все записи» — возможно, их нужно перенести.\n\n"
            + text
        )

    await edit_panel(
        message.bot, message.chat.id, text,
        master_weekly_schedule_keyboard(master_id, schedule),
        parse_mode=parse_mode,
    )


# ─── Редактирование часа конца ───────────────────────────────────────────────

@router.callback_query(F.data.startswith("msched_edit_end_"))
async def cb_msched_edit_end(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    parts = parse_callback(callback.data, "msched_edit_end", 2)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    master_id, weekday = int(parts[0]), int(parts[1])
    await state.update_data(msched_master_id=master_id, msched_weekday=weekday)
    await edit_panel_with_callback(
        callback,
        "🕕 Введите час конца работы (1–23):",
        admin_cancel_keyboard(),
    )
    await state.set_state(AdminStates.master_schedule_edit_end)
    await callback.answer()


@router.message(AdminStates.master_schedule_edit_end)
async def msg_msched_edit_end(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass
    try:
        value = int(message.text.strip())
        if not (1 <= value <= 23):
            raise ValueError
    except (ValueError, AttributeError):
        await edit_panel(
            message.bot, message.chat.id,
            "⚠️ Введите целое число от 1 до 23:",
            admin_cancel_keyboard(),
        )
        return

    data = await state.get_data()
    master_id = data["msched_master_id"]
    weekday = data["msched_weekday"]

    schedule = await get_master_schedule(master_id)
    row = schedule.get(weekday) or {}
    work_start = row.get("work_start") or 9

    if value <= work_start:
        await edit_panel(
            message.bot, message.chat.id,
            f"⚠️ Конец должен быть больше начала ({work_start:02d}:00):",
            admin_cancel_keyboard(),
        )
        return

    conflicts = await _count_master_schedule_conflicts(master_id, weekday, work_start, value)
    await update_master_weekday(master_id, weekday, work_start, value)
    await state.clear()

    master = await get_master(master_id)
    schedule = await get_master_schedule(master_id)
    text = f"📆 <b>Расписание: {master['name']}</b>\n\nВыбери день для редактирования:"
    parse_mode = "HTML"
    if conflicts > 0:
        text = (
            f"⚠️ <b>Внимание:</b> есть {conflicts} запись/записей вне новых часов работы. "
            "Проверьте «Все записи» — возможно, их нужно перенести.\n\n"
            + text
        )

    await edit_panel(
        message.bot, message.chat.id, text,
        master_weekly_schedule_keyboard(master_id, schedule),
        parse_mode=parse_mode,
    )
```

---

### Task E: Регистрация роутера в `bot.py`

**Files:**
- Modify: `bot.py` (импорт + include_router)

- [ ] **Step 1: Импорт**

В блоке импортов хендлеров найди строку:

```python
from handlers import master
```

Добавь `admin_master_schedule` в какой-то из существующих строк, например:

```python
from handlers import reviews, admin_export, admin_masters, admin_master_schedule
```

Или отдельной строкой — стиль автора.

- [ ] **Step 2: Регистрация**

Найди блок регистрации `admin_masters`/`admin_export` в `main()`. ДОБАВЬ регистрацию `admin_master_schedule.router` СРАЗУ ПОСЛЕ `admin_masters.router` (перед `admin_export.router` или после — не важно, оба admin):

```python
    dp.include_router(admin_masters.router)
    dp.include_router(admin_master_schedule.router)    # NEW
    dp.include_router(admin_export.router)
```

**Порядок критичен:** `admin_master_schedule.router` должен быть ДО `master.router`, ДО `client.router`, иначе его callbacks перехватит кто-то другой.

---

### Task F: Ручная верификация

**Files:** ничего. Автор тестирует сам.

- [ ] **Step 1: Пересбор + старт**

```bash
docker compose up -d --build
docker compose logs -f bot
```

Ожидаемо: `Бот запущен`, ни одного ERROR на старте.

- [ ] **Step 2: Сценарий — открыть расписание мастера**

1. Админ: «👨‍🎨 Мастера» → выбрать любого мастера (или создать тестового).
2. В карточке мастера появилась кнопка «📆 Расписание».
3. Клик → появляется недельная сетка с часами по каждому дню.

- [ ] **Step 3: Сценарий — toggle выходной**

1. В недельной сетке клик по любому дню (например, «Ср»).
2. Появляется детализация: «Ср 09:00 – 19:00» + кнопки «🔴 Сделать выходным» / «🕐 Час начала» / «🕕 Час конца» / «🔙 К расписанию».
3. Жми «🔴 Сделать выходным» → возвращает в сетку, среда теперь «Ср — выходной».
4. Снова клик на «Ср — выходной» → деталь → «🟢 Сделать рабочим» → возврат в сетку, среда 09:00-19:00.

- [ ] **Step 4: Сценарий — редактирование часов**

1. В детали weekday жми «🕐 Час начала» → ввод `10` → Enter.
2. Возврат в сетку, выбранный день теперь `10:00-19:00`.
3. Повтори с «🕕 Час конца» → ввод `18` → день `10:00-18:00`.
4. Ввод невалидных значений (100, -5, буквы) — бот должен показать «⚠️ Введите целое число от …».

- [ ] **Step 5: Сценарий — предупреждение о конфликте**

1. Со второго аккаунта (клиент) забронируй любую услугу у этого мастера на ближайшую среду на 09:30.
2. В админке: Мастера → мастер → Расписание → Ср → «🕐 Час начала» → ввод `11`.
3. Ожидаемо: после сохранения в сетке показывается баннер «⚠️ Внимание: есть 1 запись вне новых часов…».

- [ ] **Step 6: Сценарий — мастер видит обновление в своём кабинете**

1. Деактивируй предыдущую запись мастера, пусть он перейдёт из «Сегодня записи» в пустой.
2. В админке измени расписание мастера (например, Ср сделай выходным).
3. С аккаунта мастера нажми «📆 Моё расписание».
4. Ожидаемо: среда показывается как выходная (именно то, что админ только что установил).

- [ ] **Step 7: Изоляция мастера**

1. Мастер **не должен** видеть кнопку «📆 Расписание» в своём кабинете — только «📋 Сегодня», «📅 Мои записи», «📆 Моё расписание».
2. Мастер **не может** вызвать `msched_*` callback — его роутер фильтрует на `IsAdminFilter`. Это проверяется автоматически на уровне роутера.

- [ ] **Step 8: Финальный коммит (если все 7 сценариев прошли)**

```bash
git add db/masters.py db/__init__.py states.py keyboards/inline.py \
        handlers/admin_master_schedule.py bot.py \
        docs/superpowers/specs/2026-04-20-master-cabinet-design.md \
        docs/superpowers/plans/2026-04-20-master-schedule-admin.md && \
git commit -m "feat(admin): per-master schedule editor — toggle/start/end per weekday"
```

Если в предыдущую фазу (master cabinet) ещё не коммитили — то делаем ОДИН коммит на обе:

```bash
git add db/masters.py db/__init__.py utils/admin.py keyboards/inline.py \
        handlers/master.py handlers/client.py handlers/admin_masters.py \
        handlers/admin_master_schedule.py bot.py states.py FUTURE.md \
        docs/superpowers/specs/2026-04-20-master-cabinet-design.md \
        docs/superpowers/plans/2026-04-20-master-cabinet.md \
        docs/superpowers/plans/2026-04-20-master-schedule-admin.md && \
git commit -m "feat(master): read-only cabinet + admin per-master schedule editor"
```
