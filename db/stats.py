"""
Статистика с дельтами к предыдущему периоду — для экрана «📊 Статистика».

Зачем отдельный модуль: legacy db.get_stats() считает «всё за всю жизнь» +
сегодня/неделя/месяц-counts. Этот модуль считает агрегаты ЗА ПЕРИОД и
сравнивает с таким же предыдущим окном — даёт владельцу контекст «↑12%
к прошлому месяцу» вместо голого числа.

get_stats() не трогаем — на ней висят тесты (tests/test_appointments.py).
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from db.connection import _dict_row, _dict_rows
from utils.timezone import now_local

logger = logging.getLogger(__name__)

# Длительность периода в днях. «3 месяца» = ~90 дней (квартал).
PERIOD_DAYS: dict[str, int] = {
    "week": 7,
    "month": 30,
    "quarter": 90,
}

PERIOD_LABEL: dict[str, str] = {
    "week": "Неделя",
    "month": "Месяц",
    "quarter": "3 месяца",
}

DEFAULT_PERIOD = "month"


def _normalize_period(period: str | None) -> str:
    """Любое неизвестное значение приводим к month — защита от подделки callback."""
    return period if period in PERIOD_DAYS else DEFAULT_PERIOD


def _period_window(period: str) -> tuple[str, str, str, str]:
    """
    Окно дат для текущего и предыдущего периода (в YYYY-MM-DD).
    Текущее окно: [сегодня - days + 1, сегодня] включительно.
    Предыдущее: ровно такого же размера, заканчивается за день до текущего.
    """
    days = PERIOD_DAYS[_normalize_period(period)]
    today = now_local().date()
    cur_end = today
    cur_start = today - timedelta(days=days - 1)
    prev_end = cur_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    return (
        cur_start.isoformat(), cur_end.isoformat(),
        prev_start.isoformat(), prev_end.isoformat(),
    )


async def _period_metrics(start: str, end: str) -> dict[str, Any]:
    """
    Агрегаты записей за окно [start, end]. Один SELECT, считаем всё через
    CASE WHEN — экономия на round-trip к SQLite.

    Выручка считается только по completed-записям. service_price — base, без
    аддонов (в текущем get_stats() addons тоже не учитываются — пусть будет
    симметрично). Если потом понадобится — JOIN appointment_addons добавлю.
    """
    row = await _dict_row(
        """SELECT
            COALESCE(SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END), 0) AS completed,
            COALESCE(SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END), 0) AS cancelled,
            COALESCE(SUM(CASE WHEN status='no_show'   THEN 1 ELSE 0 END), 0) AS no_show,
            COALESCE(SUM(CASE WHEN status='completed' THEN service_price ELSE 0 END), 0) AS revenue
           FROM appointments
           WHERE date BETWEEN ? AND ?""",
        (start, end),
    )
    completed = (row or {}).get("completed", 0) or 0
    cancelled = (row or {}).get("cancelled", 0) or 0
    no_show   = (row or {}).get("no_show", 0)   or 0
    revenue   = (row or {}).get("revenue", 0)   or 0
    avg_check = (revenue / completed) if completed else 0.0
    return {
        "completed": completed,
        "cancelled": cancelled,
        "no_show": no_show,
        "revenue": revenue,
        "avg_check": avg_check,
        "total": completed + cancelled + no_show,
    }


async def _new_vs_returning(start: str, end: str) -> tuple[int, int]:
    """
    Делит клиентов в окне на «новых» (первая в их жизни не-cancelled запись
    попала в окно) и «вернувшихся» (первая запись была раньше окна).

    Один проход по всем клиентам, активным в окне, + min(date) по всему
    их хвосту записей. Дороже одного COUNT, но без этой метрики на питче
    нечего показывать в блоке «Клиенты».
    """
    rows = await _dict_rows(
        """SELECT a.user_id, MIN(a2.date) AS first_date
           FROM appointments a
           LEFT JOIN appointments a2
             ON a2.user_id = a.user_id AND a2.status != 'cancelled'
           WHERE a.date BETWEEN ? AND ? AND a.status != 'cancelled'
           GROUP BY a.user_id""",
        (start, end),
    )
    new = 0
    returning = 0
    for r in rows:
        first = r.get("first_date")
        # first_date может оказаться None если у клиента вообще нет
        # не-cancelled записей (теоретически невозможно при текущем WHERE,
        # но защищаюсь от LEFT JOIN-нюансов).
        if first is None or first >= start:
            new += 1
        else:
            returning += 1
    return new, returning


async def _top_masters(start: str, end: str, limit: int = 3) -> list[dict[str, Any]]:
    """
    Топ-мастера по выручке за окно. Рейтинг считаем по тем же completed-
    записям через LEFT JOIN reviews — без ON-фильтра по дате (рейтинг даёт
    клиент уже после визита, дата отзыва ≠ дата записи).
    """
    return await _dict_rows(
        """SELECT
            m.id, m.name,
            COALESCE(SUM(a.service_price), 0) AS revenue,
            COUNT(a.id) AS completed,
            ROUND(AVG(r.rating), 1) AS avg_rating,
            COUNT(r.id) AS reviews_count
           FROM appointments a
           JOIN masters m ON m.id = a.master_id
           LEFT JOIN reviews r ON r.appointment_id = a.id
           WHERE a.status = 'completed' AND a.date BETWEEN ? AND ?
           GROUP BY m.id, m.name
           ORDER BY revenue DESC
           LIMIT ?""",
        (start, end, limit),
    )


async def _top_service(start: str, end: str) -> dict[str, Any] | None:
    """Самая частая услуга за окно (по completed-записям)."""
    return await _dict_row(
        """SELECT service_name, COUNT(*) AS cnt
           FROM appointments
           WHERE status = 'completed' AND date BETWEEN ? AND ?
           GROUP BY service_name
           ORDER BY cnt DESC
           LIMIT 1""",
        (start, end),
    )


async def get_master_personal_stats(
    master_id: int,
    period: str = DEFAULT_PERIOD,
) -> dict[str, Any]:
    """
    Личная статистика мастера для его кабинета: completed, выручка, средний
    чек, рейтинг + дельты к предыдущему окну + место среди мастеров по
    выручке. Все агрегаты — за окно периода (week/month/quarter).

    Зачем: мастер сам видит свою ценность («я в этом месяце сделала 42
    визита, рейтинг 4.8, доход 7.8м, +5 к прошлому месяцу») — без этого
    она не верит в продукт и жалуется владельцу. Это retention-фича для
    самого продукта.

    При ошибке БД — возвращает «нулевой» payload с error-полем; хендлер
    рендерит мягкую заглушку вместо 500.
    """
    period = _normalize_period(period)
    try:
        cs, ce, ps, pe = _period_window(period)

        cur = await _dict_row(
            """SELECT
                COALESCE(SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END), 0) AS completed,
                COALESCE(SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END), 0) AS cancelled,
                COALESCE(SUM(CASE WHEN status='no_show'   THEN 1 ELSE 0 END), 0) AS no_show,
                COALESCE(SUM(CASE WHEN status='completed' THEN service_price ELSE 0 END), 0) AS revenue
               FROM appointments
               WHERE master_id = ? AND date BETWEEN ? AND ?""",
            (master_id, cs, ce),
        ) or {}
        prev = await _dict_row(
            """SELECT
                COALESCE(SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END), 0) AS completed,
                COALESCE(SUM(CASE WHEN status='completed' THEN service_price ELSE 0 END), 0) AS revenue
               FROM appointments
               WHERE master_id = ? AND date BETWEEN ? AND ?""",
            (master_id, ps, pe),
        ) or {}

        completed = cur.get("completed", 0) or 0
        revenue   = cur.get("revenue", 0) or 0
        avg_check = (revenue / completed) if completed else 0.0

        # Рейтинг и количество отзывов — за всю жизнь (ко всем записям мастера),
        # не за окно. Отзыв оставляется после визита, дата отзыва ≠ дата записи,
        # фильтрация по периоду тут только запутает. Согласовано с админ-stats.
        rating_row = await _dict_row(
            """SELECT ROUND(AVG(r.rating), 1) AS avg_rating, COUNT(r.id) AS reviews_count
               FROM reviews r
               JOIN appointments a ON a.id = r.appointment_id
               WHERE a.master_id = ?""",
            (master_id,),
        ) or {}

        # Место в рейтинге — текущий мастер vs все активные за тот же период.
        # Если мастер один — место = 1, total = 1; «#1 из 1» рендерим тонко.
        ranking = await _dict_rows(
            """SELECT m.id, COALESCE(SUM(a.service_price), 0) AS revenue
               FROM masters m
               LEFT JOIN appointments a
                 ON a.master_id = m.id AND a.status = 'completed'
                AND a.date BETWEEN ? AND ?
               WHERE m.is_active = 1
               GROUP BY m.id
               ORDER BY revenue DESC""",
            (cs, ce),
        )
        rank = None
        for i, row in enumerate(ranking, 1):
            if row["id"] == master_id:
                rank = i
                break

        return {
            "period": period,
            "completed": completed,
            "cancelled": cur.get("cancelled", 0) or 0,
            "no_show":   cur.get("no_show", 0)   or 0,
            "revenue":   revenue,
            "avg_check": avg_check,
            "prev_completed": prev.get("completed", 0) or 0,
            "prev_revenue":   prev.get("revenue", 0)   or 0,
            "avg_rating":    rating_row.get("avg_rating") or 0.0,
            "reviews_count": rating_row.get("reviews_count", 0) or 0,
            "rank": rank,
            "rank_total": len(ranking),
            "window": {"start": cs, "end": ce},
            "error": None,
        }
    except Exception as exc:
        logger.exception("get_master_personal_stats failed")
        return {
            "period": period,
            "completed": 0, "cancelled": 0, "no_show": 0,
            "revenue": 0, "avg_check": 0.0,
            "prev_completed": 0, "prev_revenue": 0,
            "avg_rating": 0.0, "reviews_count": 0,
            "rank": None, "rank_total": 0,
            "window": None,
            "error": str(exc),
        }


async def get_stats_with_trend(period: str = DEFAULT_PERIOD) -> dict[str, Any]:
    """
    Полная сводка для экрана статистики: текущее окно + предыдущее окно
    того же размера для расчёта дельт.

    При любой ошибке — возвращает «нулевой» payload с пометкой error,
    чтобы хендлер мог отрендерить деградированный экран вместо 500.
    """
    period = _normalize_period(period)
    try:
        cs, ce, ps, pe = _period_window(period)
        cur = await _period_metrics(cs, ce)
        prev = await _period_metrics(ps, pe)
        new, returning = await _new_vs_returning(cs, ce)
        top_masters = await _top_masters(cs, ce, 3)
        top_svc = await _top_service(cs, ce)
        return {
            "period": period,
            "current": cur,
            "previous": prev,
            "new_clients": new,
            "returning_clients": returning,
            "top_masters": top_masters,
            "top_service": top_svc,
            "window": {"start": cs, "end": ce, "prev_start": ps, "prev_end": pe},
            "error": None,
        }
    except Exception as exc:
        logger.exception("get_stats_with_trend failed")
        empty = {
            "completed": 0, "cancelled": 0, "no_show": 0,
            "revenue": 0, "avg_check": 0.0, "total": 0,
        }
        return {
            "period": period,
            "current": empty,
            "previous": empty,
            "new_clients": 0,
            "returning_clients": 0,
            "top_masters": [],
            "top_service": None,
            "window": None,
            "error": str(exc),
        }
