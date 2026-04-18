# Дизайн: несколько мастеров

**Дата:** 2026-04-11  
**Статус:** Согласован  

---

## Контекст

Бот записи на маникюр (aiogram 3, SQLite, APScheduler). Сейчас работает в режиме одного мастера — расписание, блокировки и записи глобальные. Цель: добавить поддержку нескольких мастеров без поломки существующей логики.

---

## Схема БД

### Новые таблицы

```sql
CREATE TABLE masters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER UNIQUE,       -- Telegram user_id для уведомлений
    name TEXT NOT NULL,
    photo_file_id TEXT DEFAULT '',
    bio TEXT DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE master_schedule (
    master_id INTEGER NOT NULL,
    weekday INTEGER NOT NULL,     -- 0=пн, 6=вс
    work_start INTEGER,           -- NULL = выходной
    work_end INTEGER,
    PRIMARY KEY (master_id, weekday),
    FOREIGN KEY (master_id) REFERENCES masters(id) ON DELETE CASCADE
);
```

### Миграции существующих таблиц

```sql
ALTER TABLE appointments ADD COLUMN master_id INTEGER REFERENCES masters(id);
ALTER TABLE blocked_slots ADD COLUMN master_id INTEGER REFERENCES masters(id);
```

- `master_id = NULL` в `appointments` — старые записи, отображаются как «Мастер не указан»
- `master_id = NULL` в `blocked_slots` — блокировка распространяется на всех мастеров

### weekly_schedule

Таблица остаётся нетронутой. При создании нового мастера её значения копируются в `master_schedule` как начальное расписание.

---

## Флоу бронирования (клиент)

**Было:** услуга → дата → время → профиль → подтверждение  
**Стало:** услуга → **мастер** → дата → время → профиль → подтверждение

### Выбор мастера
- Показываем только `is_active = 1`, отсортированных по `sort_order`
- Карточка: фото (если есть) + имя + bio
- Если мастер один — пропускаем шаг, берём его автоматически (UX-оптимизация)

### Дата и время
- Доступные дни определяются по `master_schedule` выбранного мастера (`work_start IS NOT NULL`)
- Занятые слоты: `appointments WHERE master_id = ? AND date = ? AND status = 'scheduled'`
- Заблокированные слоты: `blocked_slots WHERE (master_id = ? OR master_id IS NULL) AND date = ?`

### Подтверждение
- Отображает имя мастера
- При создании записи вызывает уведомление мастеру

---

## Функции БД (изменения)

```python
# Принимают master_id везде где раньше работали глобально
get_booked_times(date: str, master_id: int) -> list[tuple[str, int]]
is_slot_free(date: str, time: str, duration: int, master_id: int) -> bool
get_free_slots(date: str, master_id: int, service_duration: int) -> list[str]
create_appointment(..., master_id: int) -> int

# Новые
get_active_masters() -> list[dict]
get_master(master_id: int) -> dict | None
get_master_schedule(master_id: int) -> dict[int, dict]  # weekday -> {start, end}
create_master(user_id, name, photo_file_id, bio) -> int
update_master(master_id, **fields) -> None
toggle_master_active(master_id: int) -> None
seed_master_schedule(master_id: int) -> None  # копирует из weekly_schedule
```

---

## FSM: состояния записи (client)

Добавляем `master_id` в данные FSM между шагами `service_id` и `date`.

```python
class BookingStates(StatesGroup):
    choose_service = State()
    choose_master  = State()   # новый
    choose_date    = State()
    choose_time    = State()
    enter_name     = State()
    enter_phone    = State()
    confirm        = State()
```

---

## Панель администратора

### Новый раздел «Мастера»

Кнопка в главной панели: `👨‍🎨 Мастера` → callback `admin_masters`

**Список мастеров** — имя, статус (активен/нет), кнопка карточки  
**Добавить мастера** — FSM-цепочка:
1. Имя
2. Telegram user_id (с подсказкой как узнать)
3. Bio (опционально, можно пропустить)
4. Фото (опционально, можно пропустить)

**Карточка мастера:**
- Редактировать имя / user_id / bio / фото
- Активировать / деактивировать
- Кнопка «Назад»

### Изменения в существующих разделах

**Записи:** каждая карточка записи показывает имя мастера (или «—» если NULL)

**Блокировки:** при создании блока — шаг выбора мастера:
- «Для всех мастеров» (master_id = NULL)
- Конкретный мастер

**Статистика:** глобальная, без разбивки по мастерам (отложено).

---

## Уведомления мастеру

При событиях бот отправляет `bot.send_message(master.user_id, text)`:

| Событие | Текст |
|---|---|
| Новая запись | `📅 Новая запись\n👤 {name}\n💅 {service}\n🗓 {date} {time}` |
| Отмена | `❌ Отмена записи\n👤 {name}\n🗓 {date} {time}` |
| Перенос | `🔄 Перенос записи\n👤 {name}\n🗓 {old} → {new}` |

Если `master.user_id IS NULL` или отправка падает — логируем `WARNING`, не пробрасываем исключение.

---

## Обратная совместимость

- Все существующие `SELECT` из `appointments` продолжают работать — `master_id` nullable
- `get_booked_times` и `is_slot_free` — старый код не вызывается после рефакторинга клиентского флоу
- Записи с `master_id = NULL` в панели отображаются корректно через `LEFT JOIN masters`
- `weekly_schedule` не удаляется — используется как источник для `seed_master_schedule`

---

## Новые файлы

- `handlers/admin_masters.py` — управление мастерами (CRUD + FSM)

## Изменяемые файлы

- `database.py` — схема + новые функции
- `states.py` — `BookingStates.choose_master`, новые `AdminStates` для мастеров
- `handlers/client.py` — шаг выбора мастера в флоу бронирования
- `handlers/admin_appointments.py` — отображение мастера в карточках
- `handlers/admin_blocks.py` — шаг выбора мастера при блокировке
- `keyboards/inline.py` — клавиатуры выбора мастера, карточки
- `bot.py` — регистрация нового роутера

## Не трогаем

`scheduler.py`, `utils/panel.py`, `utils/admin.py`, `services.py`, `constants.py`, `config.py`
