"""CRUD отзывов клиентов."""

import logging
from typing import Any

from db.connection import get_db, _dict_row, _dict_rows

logger = logging.getLogger(__name__)


async def save_review(appointment_id: int, user_id: int, rating: int, comment: str = "") -> bool:
    """Сохранить отзыв. Возвращает False если отзыв уже существует."""
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO reviews (appointment_id, user_id, rating, comment)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(appointment_id) DO UPDATE SET
                   rating = excluded.rating,
                   comment = excluded.comment""",
            (appointment_id, user_id, rating, comment),
        )
        await db.commit()
        return True
    except Exception:
        logger.exception("save_review failed for appt_id=%s", appointment_id)
        return False


async def get_review_by_appointment(appointment_id: int) -> dict[str, Any] | None:
    """Вернуть отзыв по appointment_id или None."""
    return await _dict_row(
        "SELECT * FROM reviews WHERE appointment_id = ?",
        (appointment_id,),
    )


async def get_reviews_stats() -> dict[str, Any]:
    """Средний рейтинг и количество отзывов."""
    row = await _dict_row(
        "SELECT ROUND(AVG(rating), 1) as avg_rating, COUNT(*) as total FROM reviews"
    )
    return {
        "avg_rating": row["avg_rating"] if row and row["avg_rating"] else 0.0,
        "total": row["total"] if row else 0,
    }


async def get_all_masters_ratings() -> dict[int, dict[str, Any]]:
    """Рейтинги всех мастеров: {master_id: {avg_rating, total}}."""
    rows = await _dict_rows(
        """SELECT a.master_id,
                  ROUND(AVG(r.rating), 1) as avg_rating,
                  COUNT(r.id) as total
           FROM reviews r
           JOIN appointments a ON a.id = r.appointment_id
           WHERE a.master_id IS NOT NULL
           GROUP BY a.master_id"""
    )
    return {
        r["master_id"]: {"avg_rating": r["avg_rating"], "total": r["total"]}
        for r in rows
    }
