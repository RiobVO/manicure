"""Профили клиентов, поиск, карточка."""

from typing import Any

from db.connection import get_db, _dict_rows, _dict_row


async def get_client_profile(user_id: int) -> dict[str, Any] | None:
    return await _dict_row(
        "SELECT name, phone FROM client_profiles WHERE user_id = ?", (user_id,)
    )


async def get_user_lang(user_id: int) -> str:
    """
    Язык клиента из профиля. 'ru' по умолчанию (и для анонимов без профиля).
    Нормализация — в utils.i18n.Lang.normalize().
    """
    row = await _dict_row(
        "SELECT lang FROM client_profiles WHERE user_id = ?", (user_id,)
    )
    if row is None:
        return "ru"
    return (row.get("lang") or "ru")


async def set_user_lang(user_id: int, lang: str) -> None:
    """
    Сохранить язык клиента. Если профиля нет — создаём заглушку
    (аналогично set_client_source_if_empty в db/traffic.py): user_id +
    lang, name/phone пустые; save_client_profile позже заполнит name/phone
    через upsert, не затирая lang.
    """
    db = await get_db()
    await db.execute(
        "INSERT INTO client_profiles (user_id, name, phone, lang) "
        "VALUES (?, '', '', ?) "
        "ON CONFLICT(user_id) DO UPDATE SET lang = excluded.lang",
        (user_id, lang),
    )
    await db.commit()


async def save_client_profile(user_id: int, name: str, phone: str) -> None:
    """
    Upsert профиля: создаёт или обновляет name + phone, НЕ трогая source.
    INSERT OR REPLACE в этой роли опасен — он пересоздаёт строку и
    затирает source, который мог быть записан при /start <code> ДО
    ввода клиентом имени/телефона (см. db/traffic.py::set_client_source_if_empty).
    """
    db = await get_db()
    await db.execute(
        "INSERT INTO client_profiles (user_id, name, phone) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET name = excluded.name, phone = excluded.phone",
        (user_id, name, phone),
    )
    await db.commit()


async def get_recent_clients(limit: int = 15) -> list[dict[str, Any]]:
    """Последние N клиентов по дате активности (включая будущие записи)."""
    return await _dict_rows(
        """SELECT cp.user_id, cp.name, cp.phone,
                  MAX(a.date || ' ' || a.time) AS last_activity,
                  COUNT(CASE WHEN a.status = 'completed' THEN 1 END) AS completed_count
           FROM client_profiles cp
           LEFT JOIN appointments a ON a.user_id = cp.user_id AND a.status != 'cancelled'
           GROUP BY cp.user_id
           ORDER BY last_activity DESC
           LIMIT ?""",
        (limit,),
    )


async def search_clients(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Поиск по имени ИЛИ телефону (подстрока)."""
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    return await _dict_rows(
        """SELECT cp.user_id, cp.name, cp.phone,
                  MAX(a.date || ' ' || a.time) AS last_activity,
                  COUNT(CASE WHEN a.status = 'completed' THEN 1 END) AS completed_count
           FROM client_profiles cp
           LEFT JOIN appointments a ON a.user_id = cp.user_id AND a.status != 'cancelled'
           WHERE cp.name LIKE ? ESCAPE '\\' OR cp.phone LIKE ? ESCAPE '\\'
           GROUP BY cp.user_id
           ORDER BY last_activity DESC
           LIMIT ?""",
        (pattern, pattern, limit),
    )


async def get_dormant_clients(days: int = 30, limit: int = 20) -> list[dict[str, Any]]:
    """Клиенты, чей последний завершённый визит был более N дней назад (или не было совсем)."""
    # days подставляется в SQLite date('now', modifier) через f-string — параметризовать
    # модификатор нельзя. Жёстко фиксируем тип, чтобы будущий рефакторинг не протащил
    # user-input в этот путь и не открыл SQL-injection в date().
    if not isinstance(days, int) or isinstance(days, bool) or days < 0:
        raise ValueError(f"days must be non-negative int, got {days!r}")
    modifier = f"-{days} days"
    return await _dict_rows(
        """SELECT cp.user_id, cp.name, cp.phone,
                  MAX(CASE WHEN a.status = 'completed' THEN a.date END) AS last_visit,
                  COUNT(CASE WHEN a.status = 'completed' THEN 1 END) AS completed_count
           FROM client_profiles cp
           LEFT JOIN appointments a ON a.user_id = cp.user_id
           GROUP BY cp.user_id
           HAVING last_visit IS NULL OR last_visit < date('now', ?)
           ORDER BY last_visit ASC
           LIMIT ?""",
        (modifier, limit),
    )


async def get_client_card(user_id: int) -> dict[str, Any] | None:
    """Карточка клиента: профиль + агрегаты + последние 5 записей."""
    profile = await _dict_row(
        """SELECT cp.user_id, cp.name, cp.phone,
                  MAX(CASE WHEN a.status = 'completed' THEN a.date END) AS last_visit,
                  COUNT(CASE WHEN a.status = 'completed' THEN 1 END) AS completed_count,
                  COUNT(CASE WHEN a.status = 'scheduled' AND a.date >= date('now') THEN 1 END) AS upcoming_count,
                  COALESCE(SUM(CASE WHEN a.status = 'completed' THEN a.service_price END), 0) AS total_spent,
                  (SELECT a2.service_name FROM appointments a2
                   WHERE a2.user_id = cp.user_id AND a2.status = 'completed'
                   GROUP BY a2.service_name ORDER BY COUNT(*) DESC LIMIT 1) AS fav_service
           FROM client_profiles cp
           LEFT JOIN appointments a ON a.user_id = cp.user_id
           WHERE cp.user_id = ?
           GROUP BY cp.user_id""",
        (user_id,),
    )
    if not profile:
        return None
    profile["recent_appointments"] = await _dict_rows(
        """SELECT id, service_name, date, time, status
           FROM appointments
           WHERE user_id = ? AND status != 'cancelled'
           ORDER BY date DESC, time DESC
           LIMIT 5""",
        (user_id,),
    )
    return profile
