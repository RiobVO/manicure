"""
Глобальное подключение к БД и инициализация схемы.

• Один глобальный connection (SQLite поддерживает thread-safe access).
• Все функции используют get_db() — никогда не создавать aiosqlite.connect()
  напрямую, иначе теряется WAL-режим и появляются race-condition окна.
• row_factory НИКОГДА не меняется на глобальном connection — используется
  локальный помощник _dict_rows() через отдельный cursor.
• Защита от race condition при записи (CHECK + INSERT атомарно).
• Таблица sent_reminders — дедупликация напоминаний.
"""

import asyncio
import glob
import logging
import os
import shutil
from typing import Any, Iterable

import aiosqlite

from config import DB_PATH
from constants import DEFAULT_SETTINGS
# Импортируется только для начального seed при пустой таблице services
from db.seed import SERVICES

logger = logging.getLogger(__name__)

# ─── Глобальное подключение (переиспользуется всю жизнь бота) ───
_db: aiosqlite.Connection | None = None
_db_ready: bool = False
# Lazy: на уровне модуля нет running loop, создаётся при первом вызове.
_init_lock: asyncio.Lock | None = None
# Глобальный lock для сериализации write-транзакций (BEGIN IMMEDIATE).
_write_lock: asyncio.Lock | None = None


async def get_write_lock() -> asyncio.Lock:
    """Глобальный лок для сериализации write-транзакций.
    aiosqlite с единым connection не сериализует вложенные BEGIN IMMEDIATE,
    поэтому параллельные записи ловят OperationalError вместо бизнес-ошибки.
    """
    global _write_lock
    if _write_lock is None:
        _write_lock = asyncio.Lock()
    return _write_lock


async def get_db() -> aiosqlite.Connection:
    """Получить единый connection. Создаётся один раз при init_db()."""
    global _db, _db_ready, _init_lock
    # Быстрый путь без lock: если connection уже готов — отдаём его.
    if _db is not None and _db_ready:
        return _db
    if _init_lock is None:
        _init_lock = asyncio.Lock()
    async with _init_lock:
        # Double-checked locking: проверяем повторно под lock,
        # чтобы параллельные корутины не создали второй connection.
        if _db is None or not _db_ready:
            _db = await aiosqlite.connect(DB_PATH)
            await _db.execute("PRAGMA journal_mode=WAL")
            await _db.execute("PRAGMA foreign_keys=ON")
            _db_ready = True
    return _db


async def close_db() -> None:
    """Закрыть подключение при shutdown."""
    global _db, _db_ready, _init_lock, _write_lock
    if _db is not None:
        try:
            await _db.close()
        except Exception as exc:
            # Логируем, но не пробрасываем — мы и так на shutdown.
            logger.warning("Error closing DB connection: %s", exc)
        _db = None
        _db_ready = False
        # Сбрасываем lock: при реконнекте в том же процессе будет создан fresh.
        _init_lock = None
        # Сбрасываем write-lock, чтобы в новом процессе/loop создался заново.
        _write_lock = None


async def _dict_rows(
    sql: str, params: Iterable[Any] = ()
) -> list[dict[str, Any]]:
    """
    Выполнить SELECT и вернуть строки как список словарей.

    Создаёт локальный cursor с row_factory=aiosqlite.Row, не трогая глобальное
    состояние connection. Это устраняет race condition, когда параллельный
    запрос ожидает tuple, а получает Row (или наоборот).
    """
    db = await get_db()
    cursor = await db.execute(sql, tuple(params))
    try:
        cursor.row_factory = aiosqlite.Row
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await cursor.close()


async def _dict_row(
    sql: str, params: Iterable[Any] = ()
) -> dict[str, Any] | None:
    """Выполнить SELECT и вернуть одну строку как dict или None."""
    db = await get_db()
    cursor = await db.execute(sql, tuple(params))
    try:
        cursor.row_factory = aiosqlite.Row
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await cursor.close()


async def init_db() -> None:
    # Создание коннекшна делегируется get_db() — единственный путь открытия.
    # init_db отвечает только за схему и миграции.
    db = await get_db()

    # --- appointments ---
    await db.execute("""
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            service_id INTEGER NOT NULL,
            service_name TEXT NOT NULL,
            service_duration INTEGER NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            confirmed INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            status TEXT NOT NULL DEFAULT 'scheduled',
            service_price INTEGER NOT NULL DEFAULT 0,
            client_cancelled INTEGER NOT NULL DEFAULT 0
        )
    """)

    # --- services ---
    await db.execute("""
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            duration INTEGER NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            description TEXT DEFAULT '',
            photo_file_id TEXT DEFAULT ''
        )
    """)
    # Seed из services.py только если таблица пуста
    cursor = await db.execute("SELECT COUNT(*) FROM services")
    if (await cursor.fetchone())[0] == 0:
        await db.executemany(
            "INSERT INTO services (id, name, price, duration, is_active, sort_order) VALUES (?,?,?,?,1,?)",
            [(s["id"], s["name"], s["price"], s["duration"], i) for i, s in enumerate(SERVICES)]
        )

    # --- settings ---
    await db.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    for key, value in DEFAULT_SETTINGS.items():
        await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))

    # --- blocked_slots ---
    await db.execute("""
        CREATE TABLE IF NOT EXISTS blocked_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            time_start TEXT,
            time_end TEXT,
            is_day_off INTEGER NOT NULL DEFAULT 0,
            reason TEXT DEFAULT ''
        )
    """)

    # --- client_profiles ---
    await db.execute("""
        CREATE TABLE IF NOT EXISTS client_profiles (
            user_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT NOT NULL
        )
    """)

    # --- sent_reminders (дедуп напоминаний) ---
    await db.execute("""
        CREATE TABLE IF NOT EXISTS sent_reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            appointment_id INTEGER NOT NULL,
            reminder_type TEXT NOT NULL,
            sent_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(appointment_id, reminder_type)
        )
    """)

    # --- admin_logs (лог действий админа) ---
    await db.execute("""
        CREATE TABLE IF NOT EXISTS admin_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            target_type TEXT DEFAULT '',
            target_id INTEGER DEFAULT 0,
            details TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --- admins (дополнительные админы помимо .env) ---
    await db.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY,
            added_by INTEGER NOT NULL,
            added_at TEXT DEFAULT CURRENT_TIMESTAMP,
            comment TEXT DEFAULT ''
        )
    """)

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

    # --- weekly_schedule ---
    await db.execute("""
        CREATE TABLE IF NOT EXISTS weekly_schedule (
            weekday INTEGER PRIMARY KEY,
            work_start INTEGER,
            work_end INTEGER
        )
    """)
    # Seed: 7 дней. Если уже есть записи — не трогаем.
    # Начальные часы берём из legacy-настроек settings, иначе 9–19.
    cursor_ws = await db.execute("SELECT COUNT(*) FROM weekly_schedule")
    if (await cursor_ws.fetchone())[0] == 0:
        cursor_s = await db.execute("SELECT value FROM settings WHERE key = 'work_start'")
        start_row = await cursor_s.fetchone()
        cursor_e = await db.execute("SELECT value FROM settings WHERE key = 'work_end'")
        end_row = await cursor_e.fetchone()
        default_start = int(start_row[0]) if start_row else 9
        default_end = int(end_row[0]) if end_row else 19
        for wd in range(7):
            await db.execute(
                "INSERT INTO weekly_schedule (weekday, work_start, work_end) VALUES (?, ?, ?)",
                (wd, default_start, default_end),
            )

    # --- service_addons (доп. опции к услугам) ---
    await db.execute("""
        CREATE TABLE IF NOT EXISTS service_addons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            price INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (service_id) REFERENCES services(id) ON DELETE CASCADE
        )
    """)

    # --- appointment_addons (выбранные аддоны к записям) ---
    await db.execute("""
        CREATE TABLE IF NOT EXISTS appointment_addons (
            appointment_id INTEGER NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
            addon_id INTEGER NOT NULL REFERENCES service_addons(id),
            price INTEGER NOT NULL,
            PRIMARY KEY (appointment_id, addon_id)
        )
    """)

    # --- миграции, управляемые PRAGMA user_version ---
    # v0 → v1: колонки cancel_reason, master_id в appointments, master_id в blocked_slots.
    # Идемпотентный try/except по duplicate column оставлен, чтобы переварить
    # уже мигрированные БД, где версия не была проставлена (legacy).
    cursor_ver = await db.execute("PRAGMA user_version")
    current_version = (await cursor_ver.fetchone())[0]

    if current_version < 1:
        for stmt in (
            "ALTER TABLE appointments ADD COLUMN cancel_reason TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE appointments ADD COLUMN master_id INTEGER REFERENCES masters(id)",
            "ALTER TABLE blocked_slots ADD COLUMN master_id INTEGER REFERENCES masters(id)",
        ):
            try:
                await db.execute(stmt)
            except aiosqlite.OperationalError as exc:
                if "duplicate column" not in str(exc).lower():
                    logger.exception("Миграция v0→v1 упала: %s", stmt)
        await db.execute("PRAGMA user_version = 1")

    # --- миграция: дефолтный мастер при переходе с одно-мастерной схемы ---
    # Если таблица masters пуста — создаём одного мастера из legacy-настроек.
    cursor_m = await db.execute("SELECT COUNT(*) FROM masters")
    if (await cursor_m.fetchone())[0] == 0:
        cursor_ins = await db.execute(
            "INSERT INTO masters (user_id, name, photo_file_id, bio, is_active, sort_order) VALUES (NULL, 'Мастер', '', '', 1, 0)"
        )
        default_master_id = cursor_ins.lastrowid
        # Копируем weekly_schedule → master_schedule для дефолтного мастера
        rows_ws = await db.execute("SELECT weekday, work_start, work_end FROM weekly_schedule")
        async for row in rows_ws:
            await db.execute(
                "INSERT OR IGNORE INTO master_schedule (master_id, weekday, work_start, work_end) VALUES (?, ?, ?, ?)",
                (default_master_id, row[0], row[1], row[2]),
            )

    # --- reviews (отзывы клиентов) ---
    await db.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            appointment_id INTEGER NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
            comment TEXT NOT NULL DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (appointment_id) REFERENCES appointments(id) ON DELETE CASCADE
        )
    """)

    # --- indexes ---
    await db.execute("CREATE INDEX IF NOT EXISTS idx_appointments_date ON appointments(date)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_appointments_status ON appointments(status)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_appointments_user_id ON appointments(user_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_appointments_phone ON appointments(phone)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_blocked_slots_date ON blocked_slots(date)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_reminders_appt ON sent_reminders(appointment_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_admin_logs_created ON admin_logs(created_at)")

    await db.commit()


async def backup_db(backup_dir: str = "backups") -> str | None:
    """Создаёт бэкап БД. Ротация: последние 7 файлов."""
    try:
        os.makedirs(backup_dir, exist_ok=True)

        from utils.timezone import now_local
        timestamp = now_local().strftime("%Y-%m-%d_%H-%M")
        backup_name = f"manicure_backup_{timestamp}.db"
        backup_path = os.path.join(backup_dir, backup_name)

        # Сброс WAL перед копированием — гарантия целостности бэкапа
        db = await get_db()
        await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        shutil.copy2(DB_PATH, backup_path)

        # Ротация: оставляем только 7 последних бэкапов
        existing = sorted(glob.glob(os.path.join(backup_dir, "manicure_backup_*.db")))
        for old_file in existing[:-7]:
            try:
                os.remove(old_file)
            except OSError as exc:
                logger.warning("Не удалось удалить старый бэкап %s: %s", old_file, exc)

        logger.info("Бэкап создан: %s", backup_path)
        return backup_path
    except Exception:
        logger.error("Ошибка создания бэкапа", exc_info=True)
        return None
