"""
Общие фикстуры для pytest.

Важно: BOT_TOKEN и ADMIN_IDS должны быть выставлены ДО первого импорта
config.py — иначе модуль упадёт при старте. Делаем это на самом верху файла.
"""
import os
import sys

# ─── Выставляем env ДО любых импортов проекта ────────────────────────────────
os.environ.setdefault("BOT_TOKEN", "test_token_123:ABC")
os.environ.setdefault("ADMIN_IDS", "100,200")
os.environ.setdefault("TIMEZONE", "Asia/Tashkent")

# Добавляем корень проекта в sys.path (на всякий случай — pytest это обычно делает сам).
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import tempfile

import pytest

import config
import db.connection as dbc


def _reset_connection_globals() -> None:
    """Сброс глобального состояния connection между тестами."""
    dbc._db = None
    dbc._db_ready = False
    dbc._init_lock = None


@pytest.fixture
def temp_db_path(monkeypatch):
    """Временный файл БД. Подменяет config.DB_PATH и dbc.DB_PATH."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    # Удаляем пустой файл, чтобы SQLite сам создал с чистой схемой.
    try:
        os.remove(path)
    except OSError:
        pass

    monkeypatch.setattr(config, "DB_PATH", path, raising=False)
    monkeypatch.setattr(dbc, "DB_PATH", path, raising=False)

    yield path

    # Очистка: основной файл + WAL/SHM
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            os.remove(path + suffix)
        except OSError:
            pass


@pytest.fixture
async def fresh_db(temp_db_path):
    """
    Чистая БД с применённой схемой. Глобалы connection сброшены
    и до, и после теста — чтобы соседи не делили connection.
    """
    _reset_connection_globals()

    from db import init_db, close_db

    await init_db()
    try:
        yield
    finally:
        await close_db()
        _reset_connection_globals()


# ─── Хелперы для тестов ──────────────────────────────────────────────────────


async def _seed_master(name: str = "Анна", user_id: int | None = None) -> int:
    """Создаёт мастера со стандартным расписанием. Возвращает master_id."""
    from db import create_master
    return await create_master(user_id=user_id, name=name)


async def _seed_service(
    name: str = "Маникюр", price: int = 250000, duration: int = 60
) -> int:
    """Добавляет услугу. Возвращает service_id."""
    from db import add_service
    return await add_service(name, price, duration)


@pytest.fixture
def seed_master():
    """Фикстура-фабрика — обёртка над _seed_master."""
    return _seed_master


@pytest.fixture
def seed_service():
    return _seed_service
