# Multi-Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить поддержку нескольких мастеров: клиент выбирает мастера после услуги, у каждого мастера своё расписание и блокировки, мастер получает уведомления о записях.

**Architecture:** Новые таблицы `masters` и `master_schedule`; миграции `appointments` и `blocked_slots` (добавляется nullable `master_id`). Флоу бронирования: услуга → мастер → дата → время → профиль → подтверждение. Если мастер один — шаг выбора пропускается.

**Tech Stack:** Python 3.11, aiogram 3, aiosqlite, SQLite WAL.

---

## Карта файлов

| Файл | Действие | Суть изменений |
|---|---|---|
| `database.py` | Изменить | Схема: 2 новые таблицы + 2 миграции; новые функции для мастеров, расписания, блокировок |
| `states.py` | Изменить | `BookingStates.choose_master`; `AdminStates` для мастеров и выбора мастера при блокировке |
| `keyboards/inline.py` | Изменить | Клавиатуры выбора мастера (клиент + админ), обновить `admin_keyboard()` |
| `handlers/client.py` | Изменить | Шаг выбора мастера, обновить `choose_date` / `confirm_yes` |
| `handlers/admin_masters.py` | Создать | CRUD мастеров: список, добавление, редактирование, деактивация |
| `handlers/admin_blocks.py` | Изменить | Шаг выбора мастера перед датой блокировки |
| `handlers/admin_appointments.py` | Изменить | Показывать имя мастера в дневном виде и карточке |
| `bot.py` | Изменить | Зарегистрировать `admin_masters.router` |

---

## Task 1: DB — новые таблицы и миграции

**Files:**
- Modify: `database.py` (функция `init_db`, блок после таблицы `admins`)

- [ ] **Шаг 1.** Найти в `database.py` блок создания таблицы `admins` (строки ~195–203). После блока `# --- admins ---` и до `# --- weekly_schedule ---` вставить создание `masters` и `master_schedule`:

```python
    # --- masters ---
    await db.execute("""
        CREATE TABLE IF NOT EXISTS masters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            name TEXT NOT NULL,
            photo_file_id TEXT DEFAULT '',
            bio TEXT DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0
        )
    """)

    # --- master_schedule ---
    await db.execute("""
        CREATE TABLE IF NOT EXISTS master_schedule (
            master_id INTEGER NOT NULL,
            weekday INTEGER NOT NULL,
            work_start INTEGER,
            work_end INTEGER,
            PRIMARY KEY (master_id, weekday),
            FOREIGN KEY (master_id) REFERENCES masters(id) ON DELETE CASCADE
        )
    """)
```

- [ ] **Шаг 2.** В конец блока миграций (после `cancel_reason`) добавить миграции для `appointments` и `blocked_slots`:

```python
    # --- миграция: master_id в appointments ---
    try:
        await db.execute("ALTER TABLE appointments ADD COLUMN master_id INTEGER REFERENCES masters(id)")
    except Exception:
        pass  # колонка уже существует

    # --- миграция: master_id в blocked_slots ---
    try:
        await db.execute("ALTER TABLE blocked_slots ADD COLUMN master_id INTEGER REFERENCES masters(id)")
    except Exception:
        pass  # колонка уже существует
```

- [ ] **Шаг 3.** Запустить бот и убедиться что таблицы созданы без ошибок:

```bash
python bot.py
# Ожидание: запуск без исключений, в логах нет ERROR
# Ctrl+C для остановки
```

---

## Task 2: DB — функции CRUD мастеров

**Files:**
- Modify: `database.py` (добавить новый раздел после `# ─── WEEKLY SCHEDULE ─`)

- [ ] **Шаг 1.** В `database.py` добавить раздел с функциями мастеров. Вставить **перед** блоком `# ─── WEEKLY SCHEDULE ─`:

```python
# ─── MASTERS ─────────────────────────────────────────────────────────────────

async def get_active_masters() -> list[dict[str, Any]]:
    """Активные мастера, отсортированные по sort_order."""
    return await _dict_rows(
        "SELECT * FROM masters WHERE is_active = 1 ORDER BY sort_order, id"
    )


async def get_all_masters() -> list[dict[str, Any]]:
    """Все мастера для админ-панели."""
    return await _dict_rows(
        "SELECT * FROM masters ORDER BY sort_order, id"
    )


async def get_master(master_id: int) -> dict[str, Any] | None:
    return await _dict_row("SELECT * FROM masters WHERE id = ?", (master_id,))


async def create_master(
    user_id: int | None,
    name: str,
    photo_file_id: str = "",
    bio: str = "",
) -> int:
    """Создаёт мастера и копирует weekly_schedule как его начальное расписание."""
    db = await get_db()
    cursor = await db.execute(
        "INSERT INTO masters (user_id, name, photo_file_id, bio) VALUES (?, ?, ?, ?)",
        (user_id, name, photo_file_id, bio),
    )
    await db.commit()
    master_id = cursor.lastrowid
    await seed_master_schedule(master_id)
    return master_id


async def update_master(master_id: int, **fields: Any) -> None:
    """Обновить произвольные поля мастера. Допустимые ключи: name, user_id, photo_file_id, bio, is_active, sort_order."""
    allowed = {"name", "user_id", "photo_file_id", "bio", "is_active", "sort_order"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    db = await get_db()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    await db.execute(
        f"UPDATE masters SET {set_clause} WHERE id = ?",
        (*updates.values(), master_id),
    )
    await db.commit()


async def toggle_master_active(master_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE masters SET is_active = 1 - is_active WHERE id = ?",
        (master_id,),
    )
    await db.commit()


async def seed_master_schedule(master_id: int) -> None:
    """Копирует weekly_schedule в master_schedule для нового мастера."""
    db = await get_db()
    rows = await _dict_rows("SELECT weekday, work_start, work_end FROM weekly_schedule")
    for row in rows:
        await db.execute(
            """INSERT OR IGNORE INTO master_schedule (master_id, weekday, work_start, work_end)
               VALUES (?, ?, ?, ?)""",
            (master_id, row["weekday"], row["work_start"], row["work_end"]),
        )
    await db.commit()


async def get_master_schedule(master_id: int) -> dict[int, dict[str, Any]]:
    """Расписание мастера: {weekday: {work_start, work_end}}."""
    rows = await _dict_rows(
        "SELECT weekday, work_start, work_end FROM master_schedule WHERE master_id = ? ORDER BY weekday",
        (master_id,),
    )
    return {r["weekday"]: {"work_start": r["work_start"], "work_end": r["work_end"]} for r in rows}


async def get_day_schedule_for_master(master_id: int, date_str: str) -> tuple[int, int] | None:
    """
    Рабочие часы мастера на дату.
    Возвращает (work_start, work_end) или None если день — выходной/заблокированный.
    """
    # Явный выходной: blocked_slots с is_day_off=1 для этого мастера или глобально
    rows = await _dict_rows(
        """SELECT id FROM blocked_slots
           WHERE date = ? AND is_day_off = 1
             AND (master_id = ? OR master_id IS NULL)
        """,
        (date_str, master_id),
    )
    if rows:
        return None

    weekday = datetime.strptime(date_str, "%Y-%m-%d").weekday()
    row = await _dict_row(
        "SELECT work_start, work_end FROM master_schedule WHERE master_id = ? AND weekday = ?",
        (master_id, weekday),
    )
    if not row or row["work_start"] is None:
        return None  # выходной по расписанию

    return row["work_start"], row["work_end"]


async def get_day_off_weekdays_for_master(master_id: int) -> frozenset[int]:
    """Дни недели, помеченные выходными в расписании мастера."""
    rows = await _dict_rows(
        "SELECT weekday FROM master_schedule WHERE master_id = ? AND work_start IS NULL",
        (master_id,),
    )
    return frozenset(r["weekday"] for r in rows)


async def get_time_blocks_for_master(master_id: int, date_str: str) -> list[tuple[str, str]]:
    """Диапазоны заблокированного времени для мастера (включая глобальные блокировки)."""
    rows = await _dict_rows(
        """SELECT time_start, time_end FROM blocked_slots
           WHERE date = ? AND is_day_off = 0
             AND time_start IS NOT NULL AND time_end IS NOT NULL
             AND (master_id = ? OR master_id IS NULL)
        """,
        (date_str, master_id),
    )
    return [(r["time_start"], r["time_end"]) for r in rows]
```

---

## Task 3: DB — функции записи с master_id

**Files:**
- Modify: `database.py` (изменить `get_booked_times`, `is_slot_free`, `create_appointment`; обновить `add_day_off`, `add_time_block`)

- [ ] **Шаг 1.** Заменить `get_booked_times` (строки ~280–287):

```python
async def get_booked_times(date: str, master_id: int | None = None) -> list[tuple[str, int]]:
    """Занятые слоты для генерации свободных (только scheduled)."""
    db = await get_db()
    if master_id is not None:
        cursor = await db.execute(
            """SELECT time, service_duration FROM appointments
               WHERE date = ? AND master_id = ? AND status = 'scheduled'""",
            (date, master_id),
        )
    else:
        cursor = await db.execute(
            "SELECT time, service_duration FROM appointments WHERE date = ? AND status = 'scheduled'",
            (date,),
        )
    return await cursor.fetchall()
```

- [ ] **Шаг 2.** Заменить `is_slot_free` (строки ~290–305):

```python
async def is_slot_free(date: str, time: str, duration: int, master_id: int | None = None) -> bool:
    """
    Атомарная проверка: свободен ли слот на дату/время/мастер с учётом длительности.
    """
    db = await get_db()
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
    return count == 0
```

- [ ] **Шаг 3.** Заменить `create_appointment` (строки ~308–342). Добавить параметр `master_id`:

```python
async def create_appointment(
    user_id: int,
    name: str,
    phone: str,
    service_id: int,
    service_name: str,
    service_duration: int,
    service_price: int,
    date: str,
    time: str,
    master_id: int | None = None,
) -> None:
    """
    Создаёт запись с защитой от race condition.
    Бросает ValueError если слот уже занят.
    """
    db = await get_db()
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
        raise ValueError("Этот слот уже занят. Выберите другое время.")

    await db.execute(
        """INSERT INTO appointments
           (user_id, name, phone, service_id, service_name, service_duration,
            service_price, date, time, status, master_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', ?)""",
        (user_id, name, phone, service_id, service_name, service_duration,
         service_price, date, time, master_id),
    )
    await db.commit()
```

- [ ] **Шаг 4.** Обновить `add_day_off` и `add_time_block`, добавив параметр `master_id`:

```python
async def add_day_off(date: str, reason: str = "", master_id: int | None = None) -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO blocked_slots (date, is_day_off, reason, master_id) VALUES (?, 1, ?, ?)",
        (date, reason, master_id),
    )
    await db.commit()


async def add_time_block(
    date: str,
    time_start: str,
    time_end: str,
    reason: str = "",
    master_id: int | None = None,
) -> None:
    db = await get_db()
    await db.execute(
        """INSERT INTO blocked_slots (date, time_start, time_end, is_day_off, reason, master_id)
           VALUES (?, ?, ?, 0, ?, ?)""",
        (date, time_start, time_end, reason, master_id),
    )
    await db.commit()
```

- [ ] **Шаг 5.** Обновить `get_future_blocks` — добавить имя мастера:

```python
async def get_future_blocks() -> list[dict[str, Any]]:
    return await _dict_rows(
        """SELECT bs.id, bs.date, bs.time_start, bs.time_end, bs.is_day_off,
                  bs.reason, bs.master_id, m.name AS master_name
           FROM blocked_slots bs
           LEFT JOIN masters m ON m.id = bs.master_id
           WHERE bs.date >= date('now')
           ORDER BY bs.date, bs.time_start"""
    )
```

---

## Task 4: states.py — новые состояния

**Files:**
- Modify: `states.py`

- [ ] **Шаг 1.** В `BookingStates` добавить `choose_master` после `choose_addons`:

```python
class BookingStates(StatesGroup):
    choose_service = State()
    choose_addons = State()
    choose_master = State()   # новый
    choose_date = State()
    choose_time = State()
    confirm_profile = State()
    get_name = State()
    get_phone = State()
    confirm = State()
```

- [ ] **Шаг 2.** В `AdminStates` добавить состояния для мастеров и блокировок:

```python
    # Мастера
    master_add_name = State()
    master_add_user_id = State()
    master_add_bio = State()
    master_add_photo = State()
    master_edit_name = State()
    master_edit_user_id = State()
    master_edit_bio = State()

    # Выбор мастера при создании блокировки
    block_pick_master = State()
```

---

## Task 5: keyboards/inline.py — новые клавиатуры

**Files:**
- Modify: `keyboards/inline.py`

- [ ] **Шаг 1.** Обновить `admin_keyboard()` — добавить кнопку «Мастера» и переставить строки для симметрии (3 строки по 2 + 1 ряд):

```python
def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📋 Сегодня",      callback_data="admin_today"),
            InlineKeyboardButton(text="📅 Завтра",        callback_data="admin_tomorrow"),
        ],
        [
            InlineKeyboardButton(text="🗓 Календарь",    callback_data="admin_cal"),
            InlineKeyboardButton(text="👥 Клиенты",       callback_data="admin_clients"),
        ],
        [
            InlineKeyboardButton(text="💅 Услуги",        callback_data="admin_services"),
            InlineKeyboardButton(text="👨‍🎨 Мастера",   callback_data="admin_masters"),
        ],
        [
            InlineKeyboardButton(text="📊 Статистика",   callback_data="admin_stats"),
            InlineKeyboardButton(text="⚙️ Настройки",    callback_data="admin_settings"),
        ],
        [InlineKeyboardButton(text="🚫 Блокировки",      callback_data="admin_blocks")],
    ])
```

- [ ] **Шаг 2.** Добавить клавиатуры для клиентского выбора мастера и админ-управления (вставить **перед** `# ─── ADMIN MAIN MENU ─`):

```python
# ─── MASTER KEYBOARDS ────────────────────────────────────────────────────────

def masters_keyboard(masters: list[dict]) -> InlineKeyboardMarkup:
    """Клавиатура выбора мастера для клиента."""
    buttons = []
    for m in masters:
        name = m["name"]
        if m.get("bio"):
            name += f"  · {m['bio'][:30]}"
        buttons.append([InlineKeyboardButton(
            text=name,
            callback_data=f"master_{m['id']}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_masters_keyboard(masters: list[dict]) -> InlineKeyboardMarkup:
    """Список мастеров в панели администратора."""
    buttons = []
    for m in masters:
        status = "🟢" if m["is_active"] else "🔴"
        buttons.append([InlineKeyboardButton(
            text=f"{status} {m['name']}",
            callback_data=f"master_card_{m['id']}",
        )])
    buttons.append([InlineKeyboardButton(text="➕ Добавить мастера", callback_data="master_add")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def master_card_keyboard(master_id: int, is_active: bool) -> InlineKeyboardMarkup:
    toggle_text = "🔴 Деактивировать" if is_active else "🟢 Активировать"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Имя",    callback_data=f"master_edit_name_{master_id}"),
            InlineKeyboardButton(text="🆔 User ID", callback_data=f"master_edit_uid_{master_id}"),
        ],
        [InlineKeyboardButton(text="📝 Описание",  callback_data=f"master_edit_bio_{master_id}")],
        [InlineKeyboardButton(text=toggle_text,     callback_data=f"master_toggle_{master_id}")],
        [InlineKeyboardButton(text="🔙 К мастерам", callback_data="admin_masters")],
    ])


def block_master_select_keyboard(masters: list[dict]) -> InlineKeyboardMarkup:
    """Выбор мастера при создании блокировки."""
    buttons = [[InlineKeyboardButton(text="🌐 Все мастера", callback_data="block_master_all")]]
    for m in masters:
        buttons.append([InlineKeyboardButton(
            text=m["name"],
            callback_data=f"block_master_{m['id']}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
```

- [ ] **Шаг 3.** Обновить `blocks_list_keyboard` — показывать имя мастера рядом с блокировкой. Найти функцию `blocks_list_keyboard` и обновить формирование текста кнопки:

```python
def blocks_list_keyboard(blocks: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for b in blocks:
        if b["is_day_off"]:
            label = f"🚫 {b['date']} — весь день"
        else:
            label = f"⏰ {b['date']} {b['time_start']}–{b['time_end']}"
        # Если блокировка привязана к конкретному мастеру — показываем имя
        if b.get("master_name"):
            label += f" ({b['master_name']})"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"block_delete_{b['id']}")])
    buttons.append([InlineKeyboardButton(text="➕ Добавить", callback_data="block_add")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
```

---

## Task 6: handlers/client.py — шаг выбора мастера

**Files:**
- Modify: `handlers/client.py`

- [ ] **Шаг 1.** Добавить импорты новых функций из database и keyboards в начало файла:

В секцию `from database import ...` добавить:
```python
    get_active_masters, get_master,
    get_day_schedule_for_master, get_day_off_weekdays_for_master,
    get_time_blocks_for_master,
```

В секцию `from keyboards.inline import ...` добавить:
```python
    masters_keyboard,
```

- [ ] **Шаг 2.** Добавить вспомогательную функцию `_show_master_step` (вставить после `_day_off_weekdays()`):

```python
async def _show_master_step(
    callback: CallbackQuery,
    state: FSMContext,
    service_header: str,
) -> None:
    """
    Показывает выбор мастера. Если мастер один — пропускает шаг и сразу переходит к датам.
    service_header — уже сформированная строка с названием/ценой услуги.
    """
    masters = await get_active_masters()
    if not masters:
        try:
            await callback.message.edit_text(
                "❌ Нет доступных мастеров. Попробуйте позже или свяжитесь с нами.",
            )
        except TelegramBadRequest:
            pass
        await callback.answer()
        return

    if len(masters) == 1:
        # Единственный мастер — назначаем автоматически
        master = masters[0]
        await state.update_data(master_id=master["id"], master_name=master["name"])
        day_off_weekdays = await get_day_off_weekdays_for_master(master["id"])
        try:
            await callback.message.edit_text(
                f"{service_header}\n\n📅 Выберите дату:",
                reply_markup=dates_keyboard(day_off_weekdays),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
        await state.set_state(BookingStates.choose_date)
        await callback.answer()
        return

    try:
        await callback.message.edit_text(
            f"{service_header}\n\n👨‍🎨 Выберите мастера:",
            reply_markup=masters_keyboard(masters),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await state.set_state(BookingStates.choose_master)
    await callback.answer()
```

- [ ] **Шаг 3.** В `choose_service` (handler `BookingStates.choose_service`) заменить переход к датам на вызов `_show_master_step`. Найти блок «если нет аддонов — показываем даты»:

Было (в конце `choose_service`, блок без аддонов):
```python
    try:
        await callback.message.edit_text(
            f"<b>{service['name']}</b>{desc_line}\n"
            f"⏱ {service['duration']} мин  ·  {_price_fmt(service['price'])} сум\n\n"
            f"📅 Выберите дату:",
            reply_markup=dates_keyboard(await _day_off_weekdays()),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await state.set_state(BookingStates.choose_date)
    await callback.answer()
```

Стало:
```python
    header = (
        f"<b>{service['name']}</b>{desc_line}\n"
        f"⏱ {service['duration']} мин  ·  {_price_fmt(service['price'])} сум"
    )
    await _show_master_step(callback, state, header)
```

- [ ] **Шаг 4.** В `cb_addons_done` заменить переход к датам на вызов `_show_master_step`:

Было:
```python
    addon_line = ("   ➕ " + ", ".join(addon_names) + "\n") if addon_names else ""
    try:
        await callback.message.edit_text(
            f"<b>{data['service_name']}</b>\n"
            f"{addon_line}"
            f"⏱ {data['service_duration']} мин  ·  {_price_fmt(final_price)} сум\n\n"
            f"📅 Выберите дату:",
            reply_markup=dates_keyboard(await _day_off_weekdays()),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await state.set_state(BookingStates.choose_date)
    await callback.answer()
```

Стало:
```python
    addon_line = ("   ➕ " + ", ".join(addon_names) + "\n") if addon_names else ""
    header = (
        f"<b>{data['service_name']}</b>\n"
        f"{addon_line}"
        f"⏱ {data['service_duration']} мин  ·  {_price_fmt(final_price)} сум"
    )
    await _show_master_step(callback, state, header)
```

- [ ] **Шаг 5.** Добавить handler выбора мастера (после `cb_addons_done`):

```python
@router.callback_query(BookingStates.choose_master, F.data.startswith("master_"))
async def choose_master(callback: CallbackQuery, state: FSMContext):
    master_id = int(callback.data.split("_")[1])
    master = await get_master(master_id)
    if not master or not master["is_active"]:
        await callback.answer("Мастер недоступен. Выберите другого.", show_alert=True)
        return

    await state.update_data(master_id=master_id, master_name=master["name"])
    data = await state.get_data()

    addon_line = ("   ➕ " + ", ".join(data["addon_names"]) + "\n") if data.get("addon_names") else ""
    day_off_weekdays = await get_day_off_weekdays_for_master(master_id)
    try:
        await callback.message.edit_text(
            f"<b>{data['service_name']}</b>\n"
            f"{addon_line}"
            f"⏱ {data['service_duration']} мин  ·  {_price_fmt(data['service_price'])} сум\n"
            f"👨‍🎨 {master['name']}\n\n"
            f"📅 Выберите дату:",
            reply_markup=dates_keyboard(day_off_weekdays),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await state.set_state(BookingStates.choose_date)
    await callback.answer()
```

- [ ] **Шаг 6.** Обновить `choose_date` handler — использовать расписание мастера вместо глобального:

Найти `choose_date` (строки ~542–588). Заменить тело:

```python
@router.callback_query(BookingStates.choose_date, F.data.startswith("date_"))
async def choose_date(callback: CallbackQuery, state: FSMContext):
    date_str = callback.data.split("_", 1)[1]
    data = await state.get_data()
    duration = data["service_duration"]
    master_id: int | None = data.get("master_id")

    if master_id is not None:
        day_schedule = await get_day_schedule_for_master(master_id, date_str)
        day_off_weekdays = await get_day_off_weekdays_for_master(master_id)
        blocked_ranges = await get_time_blocks_for_master(master_id, date_str)
    else:
        day_schedule = await get_day_schedule(date_str)
        day_off_weekdays = await _day_off_weekdays()
        blocked_ranges = await get_time_blocks(date_str)

    if day_schedule is None:
        try:
            await callback.message.edit_text(
                "📵 Этот день недоступен. Выберите другую дату:",
                reply_markup=dates_keyboard(day_off_weekdays),
            )
        except TelegramBadRequest:
            pass
        await callback.answer()
        return

    work_start, work_end = day_schedule
    slot_step = int((await get_all_settings()).get("slot_step", 30))
    booked = await get_booked_times(date_str, master_id)
    free_slots = generate_free_slots(booked, duration, date_str, work_start, work_end, slot_step, blocked_ranges)

    if not free_slots:
        try:
            await callback.message.edit_text(
                "❌ На этот день нет свободных слотов. Выберите другую дату:",
                reply_markup=dates_keyboard(day_off_weekdays),
            )
        except TelegramBadRequest:
            pass
        await callback.answer()
        return

    await state.update_data(date=date_str)
    try:
        await callback.message.edit_text(
            f"📅 <b>{_date_human(date_str)}</b>\n\nВыберите время:",
            reply_markup=times_keyboard(free_slots),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await state.set_state(BookingStates.choose_time)
    await callback.answer()
```

- [ ] **Шаг 7.** Обновить экран подтверждения в `use_saved_profile` — добавить строку мастера:

```python
    master_line = f"👨‍🎨 {data['master_name']}\n" if data.get("master_name") else ""
    try:
        await callback.message.edit_text(
            f"📋 <b>Ваша запись</b>\n\n"
            f"💅 {data['service_name']}\n"
            f"{addon_line}"
            f"{master_line}"
            f"📅 {_date_human(data['date'])}  ·  {data['time']}\n"
            f"💰 {_price_fmt(data['service_price'])} сум\n\n"
            f"👤 {data['name']}  ·  {data['phone']}",
            reply_markup=confirm_keyboard(),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await state.set_state(BookingStates.confirm)
    await callback.answer()
```

В `get_phone` — найти `await message.answer(f"📋 ...")` и обновить аналогично:

```python
    master_line = f"👨‍🎨 {data['master_name']}\n" if data.get("master_name") else ""
    await message.answer(
        f"📋 <b>Ваша запись</b>\n\n"
        f"💅 {data['service_name']}\n"
        f"{addon_line}"
        f"{master_line}"
        f"📅 {_date_human(data['date'])}  ·  {data['time']}\n"
        f"💰 {_price_fmt(data['service_price'])} сум\n\n"
        f"👤 {data['name']}  ·  {data['phone']}",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML",
    )
    await message.answer("Всё верно?", reply_markup=confirm_keyboard())
    await state.set_state(BookingStates.confirm)
```

- [ ] **Шаг 8.** Обновить `confirm_yes` — передать `master_id` в `is_slot_free` и `create_appointment`, добавить уведомление мастера:

Найти вызов `is_slot_free`:
```python
    # Было:
    if not await is_slot_free(data["date"], data["time"], data["service_duration"]):
    # Стало:
    master_id: int | None = data.get("master_id")
    if not await is_slot_free(data["date"], data["time"], data["service_duration"], master_id):
```

Найти вызов `create_appointment` и добавить `master_id=master_id`:
```python
        await create_appointment(
            user_id=callback.from_user.id,
            name=data["name"],
            phone=data["phone"],
            service_id=data["service_id"],
            service_name=data["service_name"],
            service_duration=data["service_duration"],
            service_price=data["service_price"],
            date=data["date"],
            time=data["time"],
            master_id=master_id,
        )
```

После уведомления админов добавить уведомление мастеру (вставить после блока `for admin_id in ADMIN_IDS`):
```python
    # Уведомление мастеру (если у него есть Telegram user_id)
    if master_id:
        master = await get_master(master_id)
        if master and master.get("user_id") and master["user_id"] not in ADMIN_IDS:
            try:
                await callback.bot.send_message(
                    master["user_id"],
                    f"📅 <b>Новая запись</b>\n\n"
                    f"👤 {data['name']}\n"
                    f"📞 {data['phone']}\n"
                    f"💅 {data['service_name']}\n"
                    f"🗓 {date_str} в <b>{data['time']}</b>",
                    parse_mode="HTML",
                )
            except Exception:
                logger.warning("Не удалось уведомить мастера user_id=%s", master["user_id"])
```

В `cb_cancel_with_reason` после уведомления админов добавить уведомление мастера:

```python
    # Уведомление мастера об отмене
    if appt.get("master_id"):
        master = await get_master(appt["master_id"])
        if master and master.get("user_id") and master["user_id"] not in ADMIN_IDS:
            try:
                await callback.bot.send_message(
                    master["user_id"],
                    f"❌ <b>Клиент отменил запись</b>\n\n"
                    f"👤 {appt['name']}\n"
                    f"📅 {_date_human(appt['date'])}  ·  {appt['time']}\n"
                    f"💅 {appt['service_name']}"
                    f"{reason_line}",
                    parse_mode="HTML",
                )
            except Exception:
                logger.warning("Не удалось уведомить мастера об отмене user_id=%s", master["user_id"])
```

В `cb_client_cancel_reminder` добавить то же самое после уведомления админов:

```python
    # Уведомление мастера об отмене из напоминания
    if appt.get("master_id"):
        master = await get_master(appt["master_id"])
        if master and master.get("user_id") and master["user_id"] not in ADMIN_IDS:
            try:
                await callback.bot.send_message(
                    master["user_id"],
                    f"❌ <b>Клиент отменил запись</b> (из напоминания)\n\n"
                    f"👤 {appt['name']}\n"
                    f"📅 {appt['date']} в {appt['time']}\n"
                    f"💅 {appt['service_name']}",
                    parse_mode="HTML",
                )
            except Exception:
                logger.warning("Не удалось уведомить мастера об отмене user_id=%s", master["user_id"])
```

- [ ] **Шаг 9.** Обновить `cb_quick_rebook` — добавить шаг выбора мастера вместо прямого перехода к датам:

```python
@router.callback_query(F.data.regexp(r"^quick_rebook_(\d+)$"))
async def cb_quick_rebook(callback: CallbackQuery, state: FSMContext):
    """Быстрая повторная запись — берёт услугу из последней завершённой записи."""
    appt_id = int(callback.data.split("_")[2])
    appt = await get_appointment_by_id(appt_id)

    if not appt or appt["user_id"] != callback.from_user.id:
        await callback.answer("Запись не найдена.", show_alert=True)
        return

    service = await get_service_by_id(appt["service_id"])
    if not service or not service.get("is_active"):
        await callback.answer("Эта услуга больше не доступна.", show_alert=True)
        return

    await state.clear()
    await state.update_data(
        service_id=service["id"],
        service_name=service["name"],
        service_duration=service["duration"],
        service_price=service["price"],
        selected_addons=[],
    )

    profile = await get_client_profile(callback.from_user.id)
    if profile:
        await state.update_data(name=profile["name"], phone=profile["phone"])

    header = f"🔁 <b>Повторная запись</b>\n💅 {service['name']}"
    await _show_master_step(callback, state, header)
```

---

## Task 7: handlers/admin_masters.py — новый файл

**Files:**
- Create: `handlers/admin_masters.py`

- [ ] **Шаг 1.** Создать файл:

```python
import logging

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database import (
    get_all_masters, get_master,
    create_master, update_master, toggle_master_active,
)
from keyboards.inline import admin_masters_keyboard, master_card_keyboard, admin_cancel_keyboard
from states import AdminStates
from utils.admin import is_admin_callback, is_admin_message, deny_access
from utils.panel import edit_panel, edit_panel_with_callback

logger = logging.getLogger(__name__)
router = Router()


async def _show_masters(callback: CallbackQuery) -> None:
    masters = await get_all_masters()
    text = f"👨‍🎨 Мастера ({len(masters)})" if masters else "👨‍🎨 Мастера\n\nНет ни одного мастера."
    await edit_panel_with_callback(callback, text, admin_masters_keyboard(masters))


@router.callback_query(F.data == "admin_masters")
async def cb_admin_masters(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    await state.clear()
    await _show_masters(callback)
    await callback.answer()


@router.callback_query(F.data.startswith("master_card_"))
async def cb_master_card(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    master_id = int(callback.data.split("_")[2])
    master = await get_master(master_id)
    if not master:
        await callback.answer("Мастер не найден.", show_alert=True)
        return

    uid_line = f"🆔 TG: {master['user_id']}\n" if master.get("user_id") else "🆔 TG: не привязан\n"
    bio_line = f"📝 {master['bio']}\n" if master.get("bio") else ""
    status = "🟢 Активен" if master["is_active"] else "🔴 Неактивен"

    text = (
        f"👨‍🎨 <b>{master['name']}</b>\n\n"
        f"{uid_line}"
        f"{bio_line}"
        f"{status}"
    )
    await edit_panel_with_callback(
        callback, text,
        master_card_keyboard(master_id, bool(master["is_active"])),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("master_toggle_"))
async def cb_master_toggle(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    master_id = int(callback.data.split("_")[2])
    await toggle_master_active(master_id)
    await cb_master_card(callback)


# ─── ДОБАВЛЕНИЕ МАСТЕРА ───────────────────────────────────────────────────────

@router.callback_query(F.data == "master_add")
async def cb_master_add(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    await edit_panel_with_callback(callback, "👨‍🎨 Введите имя мастера:", admin_cancel_keyboard())
    await state.set_state(AdminStates.master_add_name)
    await callback.answer()


@router.message(AdminStates.master_add_name)
async def msg_master_add_name(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass
    name = message.text.strip() if message.text else ""
    if not name or len(name) < 2:
        await edit_panel(message.bot, message.chat.id, "⚠️ Имя слишком короткое. Введите имя мастера:", admin_cancel_keyboard())
        return
    await state.update_data(master_name=name)
    await edit_panel(
        message.bot, message.chat.id,
        f"👤 Мастер: <b>{name}</b>\n\n"
        "Введите Telegram user_id мастера\n"
        "<i>(узнать можно через @userinfobot — перешлите ему сообщение от мастера)</i>\n\n"
        "Или нажмите /skip чтобы пропустить:",
        admin_cancel_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(AdminStates.master_add_user_id)


@router.message(AdminStates.master_add_user_id)
async def msg_master_add_user_id(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass

    text = message.text.strip() if message.text else ""
    user_id: int | None = None

    if text != "/skip":
        if not text.lstrip("-").isdigit():
            await edit_panel(message.bot, message.chat.id, "⚠️ Введите числовой user_id или /skip:", admin_cancel_keyboard())
            return
        user_id = int(text)

    await state.update_data(master_user_id=user_id)
    await edit_panel(
        message.bot, message.chat.id,
        "📝 Введите краткое описание мастера (специализация, стаж и т.п.)\n\nИли /skip:",
        admin_cancel_keyboard(),
    )
    await state.set_state(AdminStates.master_add_bio)


@router.message(AdminStates.master_add_bio)
async def msg_master_add_bio(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass

    text = message.text.strip() if message.text else ""
    bio = "" if text == "/skip" else text

    data = await state.get_data()
    master_id = await create_master(
        user_id=data.get("master_user_id"),
        name=data["master_name"],
        bio=bio,
    )
    await state.clear()

    master = await get_master(master_id)
    masters = await get_all_masters()
    await edit_panel(
        message.bot, message.chat.id,
        f"✅ Мастер <b>{master['name']}</b> добавлен.\n\n"
        f"👨‍🎨 Мастера ({len(masters)})",
        admin_masters_keyboard(masters),
        parse_mode="HTML",
    )


# ─── РЕДАКТИРОВАНИЕ ──────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("master_edit_name_"))
async def cb_master_edit_name(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    master_id = int(callback.data.split("_")[3])
    await state.update_data(edit_master_id=master_id)
    await edit_panel_with_callback(callback, "✏️ Введите новое имя:", admin_cancel_keyboard())
    await state.set_state(AdminStates.master_edit_name)
    await callback.answer()


@router.message(AdminStates.master_edit_name)
async def msg_master_edit_name(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass
    name = message.text.strip() if message.text else ""
    if not name or len(name) < 2:
        await edit_panel(message.bot, message.chat.id, "⚠️ Имя слишком короткое:", admin_cancel_keyboard())
        return
    data = await state.get_data()
    master_id = data["edit_master_id"]
    await update_master(master_id, name=name)
    await state.clear()
    master = await get_master(master_id)
    await edit_panel(
        message.bot, message.chat.id,
        f"✅ Имя обновлено: <b>{master['name']}</b>",
        master_card_keyboard(master_id, bool(master["is_active"])),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("master_edit_uid_"))
async def cb_master_edit_uid(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    master_id = int(callback.data.split("_")[3])
    await state.update_data(edit_master_id=master_id)
    await edit_panel_with_callback(
        callback,
        "🆔 Введите новый Telegram user_id мастера\nИли /skip чтобы убрать привязку:",
        admin_cancel_keyboard(),
    )
    await state.set_state(AdminStates.master_edit_user_id)
    await callback.answer()


@router.message(AdminStates.master_edit_user_id)
async def msg_master_edit_user_id(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass
    text = message.text.strip() if message.text else ""
    user_id: int | None = None
    if text != "/skip":
        if not text.lstrip("-").isdigit():
            await edit_panel(message.bot, message.chat.id, "⚠️ Введите числовой user_id или /skip:", admin_cancel_keyboard())
            return
        user_id = int(text)
    data = await state.get_data()
    master_id = data["edit_master_id"]
    await update_master(master_id, user_id=user_id)
    await state.clear()
    master = await get_master(master_id)
    await edit_panel(
        message.bot, message.chat.id,
        "✅ User ID обновлён.",
        master_card_keyboard(master_id, bool(master["is_active"])),
    )


@router.callback_query(F.data.startswith("master_edit_bio_"))
async def cb_master_edit_bio(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    master_id = int(callback.data.split("_")[3])
    await state.update_data(edit_master_id=master_id)
    await edit_panel_with_callback(callback, "📝 Введите новое описание (или /skip чтобы очистить):", admin_cancel_keyboard())
    await state.set_state(AdminStates.master_edit_bio)
    await callback.answer()


@router.message(AdminStates.master_edit_bio)
async def msg_master_edit_bio(message: Message, state: FSMContext):
    if not is_admin_message(message):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass
    text = message.text.strip() if message.text else ""
    bio = "" if text == "/skip" else text
    data = await state.get_data()
    master_id = data["edit_master_id"]
    await update_master(master_id, bio=bio)
    await state.clear()
    master = await get_master(master_id)
    await edit_panel(
        message.bot, message.chat.id,
        "✅ Описание обновлено.",
        master_card_keyboard(master_id, bool(master["is_active"])),
    )
```

---

## Task 8: handlers/admin_blocks.py — выбор мастера

**Files:**
- Modify: `handlers/admin_blocks.py`

- [ ] **Шаг 1.** Добавить импорты:

```python
from database import get_future_blocks, add_day_off, add_time_block, delete_blocked_slot, get_active_masters
from keyboards.inline import (
    blocks_list_keyboard, block_date_keyboard, block_type_keyboard,
    block_delete_confirm_keyboard, admin_cancel_keyboard,
    block_master_select_keyboard,
)
```

- [ ] **Шаг 2.** Изменить `cb_block_add` — добавить шаг выбора мастера перед датой:

```python
@router.callback_query(F.data == "block_add")
async def cb_block_add(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    masters = await get_active_masters()
    if masters:
        await edit_panel_with_callback(
            callback,
            "📵 Для кого создать блокировку?",
            block_master_select_keyboard(masters),
        )
        await state.set_state(AdminStates.block_pick_master)
    else:
        # Нет мастеров — сразу к дате, master_id=None
        await state.update_data(block_master_id=None)
        await edit_panel_with_callback(callback, "📵 Выберите дату для блокировки:", block_date_keyboard())
        await state.set_state(AdminStates.block_pick_date)
    await callback.answer()
```

- [ ] **Шаг 3.** Добавить handler выбора мастера для блокировки (перед `cb_block_date`):

```python
@router.callback_query(AdminStates.block_pick_master, F.data.startswith("block_master_"))
async def cb_block_master(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    raw = callback.data.split("_")[2]
    master_id = None if raw == "all" else int(raw)
    await state.update_data(block_master_id=master_id)
    await edit_panel_with_callback(callback, "📵 Выберите дату для блокировки:", block_date_keyboard())
    await state.set_state(AdminStates.block_pick_date)
    await callback.answer()
```

- [ ] **Шаг 4.** Обновить `cb_block_type_dayoff` — передавать `master_id` в `add_day_off`:

```python
@router.callback_query(AdminStates.block_pick_type, F.data.startswith("block_type_dayoff_"))
async def cb_block_type_dayoff(callback: CallbackQuery, state: FSMContext):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    date_str = callback.data.split("_", 3)[3]
    data = await state.get_data()
    master_id = data.get("block_master_id")
    await add_day_off(date_str, master_id=master_id)
    await state.clear()
    await callback.answer("Выходной добавлен.", show_alert=False)
    await _show_blocks(callback)
```

- [ ] **Шаг 5.** Обновить `msg_block_time_end` — передавать `master_id` в `add_time_block`:

В конце `msg_block_time_end` найти `await add_time_block(date_str, time_start, text)` и заменить:
```python
    data = await state.get_data()
    time_start = data["block_time_start"]
    date_str = data["block_date"]
    master_id = data.get("block_master_id")
    # ...
    await add_time_block(date_str, time_start, text, master_id=master_id)
```

---

## Task 9: handlers/admin_appointments.py — показывать мастера

**Files:**
- Modify: `handlers/admin_appointments.py`

- [ ] **Шаг 1.** В `_build_day_view` обновить запрос — `get_appointments_by_date_full` теперь включает `master_id`. Добавить в отображение каждой записи строку мастера:

В `database.py` обновить `get_appointments_by_date_full`:
```python
async def get_appointments_by_date_full(date: str) -> list[dict[str, Any]]:
    return await _dict_rows(
        """SELECT a.id, a.user_id, a.name, a.phone, a.service_name, a.service_duration,
                  a.service_price, a.date, a.time, a.status, a.client_cancelled,
                  a.master_id, m.name AS master_name
           FROM appointments a
           LEFT JOIN masters m ON m.id = a.master_id
           WHERE a.date = ?
           ORDER BY a.time""",
        (date,),
    )
```

- [ ] **Шаг 2.** В `_build_day_view` добавить строку мастера в отображение каждой записи. Найти блок формирования строки scheduled-записи:

```python
        for a in scheduled:
            master_line = f"\n   👨‍🎨 {a['master_name']}" if a.get("master_name") else ""
            lines.append(
                f"\n🕐 {a['time']} — {a['name']}\n"
                f"   📞 {a['phone']}\n"
                f"   💅 {a['service_name']}"
                f"{master_line}"
            )
```

- [ ] **Шаг 3.** В `cb_appt_detail` (в `admin_clients.py`) добавить строку мастера. Обновить `get_appointment_by_id` в `database.py`:

```python
async def get_appointment_by_id(appointment_id: int) -> dict[str, Any] | None:
    return await _dict_row(
        """SELECT a.*, m.name AS master_name
           FROM appointments a
           LEFT JOIN masters m ON m.id = a.master_id
           WHERE a.id = ?""",
        (appointment_id,),
    )
```

В `cb_appt_detail` добавить строку мастера в текст:
```python
    master_line = f"\n👨‍🎨 {appt['master_name']}" if appt.get("master_name") else ""
    text = (
        f"📋 Запись #{appt['id']}\n\n"
        f"👤 {appt['name']}\n"
        f"📞 {appt['phone']}\n"
        f"💅 {appt['service_name']}\n"
        f"📅 {appt['date']} в {appt['time']}"
        f"{master_line}\n"
        f"📌 {status}"
    )
```

---

## Task 10: bot.py — регистрация роутера

**Files:**
- Modify: `bot.py`

- [ ] **Шаг 1.** Добавить импорт и регистрацию роутера. В импортах добавить:

```python
from handlers import admin_masters
```

В `main()` после `dp.include_router(admin_manage.router)`:
```python
    dp.include_router(admin_masters.router)
```

---

## Task 11: Финальная проверка

- [ ] **Шаг 1.** Запустить бот:

```bash
python bot.py
# Ожидание: запуск без ошибок импорта и БД
```

- [ ] **Шаг 2.** Через Telegram проверить клиентский флоу:
  - `/start` → выбор услуги → убедиться что появляется шаг «Выберите мастера» (или пропускается если мастер один)
  - Пройти флоу до конца → запись создана, в подтверждении видно имя мастера

- [ ] **Шаг 3.** Через Telegram проверить админ-панель:
  - Кнопка «👨‍🎨 Мастера» присутствует в главном меню
  - Добавить мастера → проверить список
  - Деактивировать мастера → в клиентском флоу он не отображается

- [ ] **Шаг 4.** Проверить блокировки:
  - Добавить блокировку → появляется шаг выбора мастера («Все» или конкретный)
  - В списке блокировок отображается имя мастера если выбран конкретный
