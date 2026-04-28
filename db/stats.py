"""
Агрегаты для админских экранов: home-counters, статистика с трендом и т.п.

Вынесено отдельно от db/connection.py, чтобы не раздувать монолитный модуль —
эти функции вызываются из конкретных хендлеров и могут эволюционировать
(добавляться периоды, фильтры) без риска тронуть схему/init_db.
"""
from __future__ import annotations

import logging
from typing import Any

from db.connection import _dict_row

logger = logging.getLogger(__name__)


async def get_home_counters() -> dict[str, Any]:
    """
    Лёгкие счётчики для главного экрана админ-панели.
    Один SELECT на каждый счётчик, без JOIN — выполняется за миллисекунды
    даже на «жирных» БД (десятки тысяч записей).

    При любой ошибке БД возвращает нули — главный экран не должен падать
    из-за подсчётов.
    """
    counters: dict[str, Any] = {
        "today_count": 0,
        "upcoming_count": 0,
        "services_count": 0,
        "masters_count": 0,
        "reviews_avg": 0.0,
        "reviews_count": 0,
    }
    try:
        # Сегодня — scheduled-записи на текущую дату по локальному времени БД.
        # date('now', 'localtime') берёт системное время контейнера, которое в
        # docker-compose выставлено в TZ из .env (Asia/Tashkent по дефолту).
        row = await _dict_row(
            "SELECT COUNT(*) AS n FROM appointments "
            "WHERE date = date('now', 'localtime') AND status = 'scheduled'"
        )
        counters["today_count"] = (row or {}).get("n", 0)

        # Грядущее — все scheduled от сегодняшнего дня и дальше.
        row = await _dict_row(
            "SELECT COUNT(*) AS n FROM appointments "
            "WHERE date >= date('now', 'localtime') AND status = 'scheduled'"
        )
        counters["upcoming_count"] = (row or {}).get("n", 0)

        row = await _dict_row(
            "SELECT COUNT(*) AS n FROM services WHERE is_active = 1"
        )
        counters["services_count"] = (row or {}).get("n", 0)

        row = await _dict_row(
            "SELECT COUNT(*) AS n FROM masters WHERE is_active = 1"
        )
        counters["masters_count"] = (row or {}).get("n", 0)

        row = await _dict_row(
            "SELECT ROUND(AVG(rating), 1) AS avg_r, COUNT(*) AS n FROM reviews"
        )
        if row:
            counters["reviews_avg"] = row.get("avg_r") or 0.0
            counters["reviews_count"] = row.get("n", 0)
    except Exception:
        # Не подсунем падение наверх: home-экран рендерится с нулями.
        # Лог в error-канал админу — пусть видит проблему, но бот живой.
        logger.exception("get_home_counters failed; возвращаю нули")

    return counters
