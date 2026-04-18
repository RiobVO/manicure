"""Тесты is_admin, IsAdminFilter и кэша админов из БД."""
from types import SimpleNamespace

import pytest

import config
import utils.admin as admin_utils
from utils.admin import is_admin, all_admin_ids, IsAdminFilter


def test_is_admin_env_only(monkeypatch):
    """ADMIN_IDS содержит {100} → is_admin(100) True, is_admin(999) False."""
    monkeypatch.setattr(config, "ADMIN_IDS", frozenset({100}))
    monkeypatch.setattr(admin_utils, "ADMIN_IDS", frozenset({100}))
    monkeypatch.setattr(admin_utils, "_db_admins_cache", set())

    assert is_admin(100) is True
    assert is_admin(999) is False


def test_is_admin_with_db_cache(monkeypatch):
    """Пользователь только в БД-кэше → is_admin True."""
    monkeypatch.setattr(config, "ADMIN_IDS", frozenset())
    monkeypatch.setattr(admin_utils, "ADMIN_IDS", frozenset())
    monkeypatch.setattr(admin_utils, "_db_admins_cache", {555})

    assert is_admin(555) is True
    assert is_admin(777) is False


def test_all_admin_ids_union(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_IDS", frozenset({100, 200}))
    monkeypatch.setattr(admin_utils, "ADMIN_IDS", frozenset({100, 200}))
    monkeypatch.setattr(admin_utils, "_db_admins_cache", {300, 400})

    result = all_admin_ids()
    assert result == {100, 200, 300, 400}


async def test_IsAdminFilter_matches(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_IDS", frozenset({100}))
    monkeypatch.setattr(admin_utils, "ADMIN_IDS", frozenset({100}))
    monkeypatch.setattr(admin_utils, "_db_admins_cache", set())

    filt = IsAdminFilter()
    event = SimpleNamespace(from_user=SimpleNamespace(id=100))
    assert await filt(event) is True


async def test_IsAdminFilter_rejects(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_IDS", frozenset({100}))
    monkeypatch.setattr(admin_utils, "ADMIN_IDS", frozenset({100}))
    monkeypatch.setattr(admin_utils, "_db_admins_cache", set())

    filt = IsAdminFilter()
    event = SimpleNamespace(from_user=SimpleNamespace(id=42))
    assert await filt(event) is False


async def test_IsAdminFilter_no_user(monkeypatch):
    """Событие без from_user → False."""
    filt = IsAdminFilter()
    event = SimpleNamespace(from_user=None)
    assert await filt(event) is False
