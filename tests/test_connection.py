"""Тесты connection-слоя: get_db, init_db, close_db, миграции, PRAGMA."""
import asyncio

import db.connection as dbc
from db import init_db, close_db, get_db


async def test_get_db_returns_same_connection(fresh_db):
    """Два последовательных get_db должны вернуть один и тот же объект."""
    db1 = await get_db()
    db2 = await get_db()
    assert db1 is db2


async def test_get_db_concurrent_no_double_init(temp_db_path):
    """10 параллельных get_db создают ровно один connection (double-checked lock)."""
    dbc._db = None
    dbc._db_ready = False
    dbc._init_lock = None

    await init_db()
    try:
        results = await asyncio.gather(*[get_db() for _ in range(10)])
        assert all(c is results[0] for c in results)
        assert dbc._db_ready is True
    finally:
        await close_db()
        dbc._db = None
        dbc._db_ready = False
        dbc._init_lock = None


async def test_close_db_resets_state(temp_db_path):
    dbc._db = None
    dbc._db_ready = False
    dbc._init_lock = None

    await init_db()
    assert dbc._db is not None
    assert dbc._db_ready is True

    await close_db()
    assert dbc._db is None
    assert dbc._db_ready is False
    assert dbc._init_lock is None


async def test_init_db_creates_all_tables(fresh_db):
    """Проверяем наличие всех ожидаемых таблиц."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    rows = await cursor.fetchall()
    names = {r[0] for r in rows}

    expected = {
        "appointments",
        "services",
        "settings",
        "blocked_slots",
        "client_profiles",
        "sent_reminders",
        "admin_logs",
        "admins",
        "masters",
        "master_schedule",
        "weekly_schedule",
        "service_addons",
        "appointment_addons",
        "reviews",
    }
    missing = expected - names
    assert not missing, f"Отсутствуют таблицы: {missing}"


async def test_init_db_idempotent(temp_db_path):
    """init_db дважды — никаких ошибок, схема остаётся целой."""
    dbc._db = None
    dbc._db_ready = False
    dbc._init_lock = None

    await init_db()
    # Второй вызов — не должен падать (все CREATE TABLE IF NOT EXISTS).
    await init_db()

    db = await get_db()
    cursor = await db.execute("SELECT COUNT(*) FROM appointments")
    assert (await cursor.fetchone())[0] == 0

    await close_db()
    dbc._db = None
    dbc._db_ready = False
    dbc._init_lock = None


async def test_migrations_add_column_ok(temp_db_path):
    """
    Миграции ALTER TABLE (cancel_reason, master_id) должны быть идемпотентны:
    второй запуск init_db не должен падать, а только логировать 'duplicate column'.
    """
    dbc._db = None
    dbc._db_ready = False
    dbc._init_lock = None

    await init_db()
    await init_db()  # второй прогон — миграции пропускаются без исключения

    db = await get_db()
    cursor = await db.execute("PRAGMA table_info(appointments)")
    cols = {row[1] for row in await cursor.fetchall()}
    assert "cancel_reason" in cols
    assert "master_id" in cols

    cursor = await db.execute("PRAGMA table_info(blocked_slots)")
    cols2 = {row[1] for row in await cursor.fetchall()}
    assert "master_id" in cols2

    await close_db()
    dbc._db = None
    dbc._db_ready = False
    dbc._init_lock = None


async def test_pragma_foreign_keys_on(fresh_db):
    db = await get_db()
    cursor = await db.execute("PRAGMA foreign_keys")
    val = (await cursor.fetchone())[0]
    assert val == 1


async def test_pragma_journal_mode_wal(fresh_db):
    db = await get_db()
    cursor = await db.execute("PRAGMA journal_mode")
    val = (await cursor.fetchone())[0]
    assert val.lower() == "wal"
