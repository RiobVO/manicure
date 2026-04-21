"""
Источники трафика (deep-link attribution). Phase 2 v.4.

traffic_sources — справочник кодов («desk», «ig_bio», «story_april20» и т.п.)
с человекочитаемым label. client_profiles.source фиксируется при первом
/start <code> клиента и не переписывается: если один человек сначала пришёл
со story, а потом сосканировал QR на ресепшне, атрибуция остаётся
«story» — второе касание не считается новым источником.
"""
from __future__ import annotations

import re
from typing import Any

from db.connection import _dict_row, _dict_rows, get_db

# Допустимые символы кода источника: только ASCII [a-z0-9_-], 2..32 симв.
# Причина: код идёт в URL (t.me/bot?start=<code>), а Telegram принимает
# только URL-safe символы. Регистр нормализуем до lowercase.
_CODE_RE = re.compile(r"^[a-z0-9_-]{2,32}$")


def normalize_code(raw: str) -> str | None:
    """Вернуть нормализованный код или None если формат невалиден."""
    if not raw:
        return None
    code = raw.strip().lower()
    return code if _CODE_RE.fullmatch(code) else None


async def list_sources() -> list[dict[str, Any]]:
    """Все источники, отсортированные по дате создания (свежие внизу)."""
    return await _dict_rows(
        "SELECT id, code, label, created_at FROM traffic_sources ORDER BY id ASC"
    )


async def get_source_by_code(code: str) -> dict[str, Any] | None:
    return await _dict_row(
        "SELECT id, code, label FROM traffic_sources WHERE code = ?",
        (code,),
    )


async def get_source_by_id(source_id: int) -> dict[str, Any] | None:
    return await _dict_row(
        "SELECT id, code, label, created_at FROM traffic_sources WHERE id = ?",
        (source_id,),
    )


async def create_source(code: str, label: str) -> int | None:
    """
    Создать источник. None если code уже существует (UNIQUE constraint).
    Валидация code — в normalize_code(); label обрезаем до 64 симв.
    """
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO traffic_sources (code, label) VALUES (?, ?)",
            (code, label[:64]),
        )
        await db.commit()
        return cursor.lastrowid
    except Exception:
        return None


async def delete_source(source_id: int) -> bool:
    """
    Удалить источник из справочника. client_profiles.source остаётся
    как есть (это исторический факт, а не FK) — если админ удалил источник,
    старые клиенты продолжают считаться пришедшими с того кода, но он уже
    не появится в списке для новых QR.
    """
    db = await get_db()
    cursor = await db.execute(
        "DELETE FROM traffic_sources WHERE id = ?", (source_id,)
    )
    await db.commit()
    return cursor.rowcount > 0


async def set_client_source_if_empty(user_id: int, code: str) -> bool:
    """
    Записать source в профиль клиента — ТОЛЬКО если там ещё NULL.
    Возвращает True если записали, False если профиль уже атрибутирован
    (или не существует — для нового клиента профиль создастся позже
    при save_client_profile, source останется NULL до следующего /start
    с payload'ом; чтобы этого избежать, мы также вставляем заглушку).

    Особый случай: профиля ещё нет (клиент первый раз открыл бота и не
    дошёл до ввода имени) — создаём заготовку user_id + source, name/phone
    пустые. save_client_profile потом сделает INSERT OR REPLACE, но source
    мы сохраним через отдельный путь: save_client_profile_preserve_source
    не нужен — мы сделали INSERT с пустыми полями, а последующий
    INSERT OR REPLACE перетрёт source. Чтобы этого не было — save_client_profile
    обновлён через UPDATE, см. db/clients.py.
    """
    db = await get_db()
    cursor = await db.execute(
        "SELECT source FROM client_profiles WHERE user_id = ?", (user_id,)
    )
    row = await cursor.fetchone()
    if row is None:
        # Профиля ещё нет — создаём заглушку с source, name/phone пустые.
        # save_client_profile позже заполнит name/phone через UPDATE.
        await db.execute(
            "INSERT INTO client_profiles (user_id, name, phone, source) "
            "VALUES (?, '', '', ?)",
            (user_id, code),
        )
        await db.commit()
        return True
    if row[0]:
        # Уже атрибутирован — не переписываем.
        return False
    await db.execute(
        "UPDATE client_profiles SET source = ? WHERE user_id = ?",
        (code, user_id),
    )
    await db.commit()
    return True


async def aggregate_by_source() -> list[dict[str, Any]]:
    """
    Агрегат по источникам: клиентов, записей (scheduled + completed),
    суммарная выручка (только completed — запланированные ещё не «дошли»).
    Источники без клиентов тоже возвращаем (clients=0) — админу видно,
    что QR на двери пока не выстрелил.
    """
    return await _dict_rows(
        """SELECT ts.id, ts.code, ts.label,
                  COUNT(DISTINCT cp.user_id) AS clients_count,
                  COUNT(a.id) AS bookings_count,
                  COALESCE(SUM(CASE WHEN a.status = 'completed'
                                    THEN a.service_price END), 0) AS revenue
           FROM traffic_sources ts
           LEFT JOIN client_profiles cp ON cp.source = ts.code
           LEFT JOIN appointments a ON a.user_id = cp.user_id
                                    AND a.status != 'cancelled'
           GROUP BY ts.id
           ORDER BY clients_count DESC, ts.id ASC"""
    )
