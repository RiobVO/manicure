"""CRUD записей (appointments): создание, поиск, статусы, статистика, экспорт."""

from typing import Any

from utils.timezone import now_local
from db.connection import get_db, _dict_rows, _dict_row, get_write_lock


async def get_booked_times(date: str, master_id: int | None = None) -> list[tuple[str, int]]:
    """Занятые слоты для генерации свободных (только scheduled)."""
    db = await get_db()
    if master_id is not None:
        cursor = await db.execute(
            """SELECT time, service_duration FROM appointments
               WHERE date = ? AND master_id = ? AND status = 'scheduled'""",
            (date, master_id),
        )
    else:
        cursor = await db.execute(
            "SELECT time, service_duration FROM appointments WHERE date = ? AND status = 'scheduled'",
            (date,),
        )
    return await cursor.fetchall()


async def create_appointment(
    user_id: int, name: str, phone: str,
    service_id: int, service_name: str, service_duration: int,
    service_price: int, date: str, time: str,
    master_id: int | None = None,
) -> int:
    """
    Создаёт запись атомарно (BEGIN IMMEDIATE).
    Бросает ValueError если слот занят.
    Возвращает ID созданной записи.
    """
    db = await get_db()
    lock = await get_write_lock()
    # Lock нужен из-за ограничения aiosqlite: на одном connection
    # параллельные BEGIN IMMEDIATE дают OperationalError, а не бизнес-ошибку.
    async with lock:
        await db.execute("BEGIN IMMEDIATE")
        try:
            if master_id is not None:
                cursor = await db.execute(
                    """SELECT COUNT(*) FROM appointments
                       WHERE date = ? AND master_id = ? AND status = 'scheduled'
                         AND datetime(date || ' ' || time)
                             < datetime(date || ' ' || ?, '+' || ? || ' minutes')
                         AND datetime(date || ' ' || time, '+' || service_duration || ' minutes')
                             > datetime(date || ' ' || ?)
                    """,
                    (date, master_id, time, service_duration, time),
                )
            else:
                cursor = await db.execute(
                    """SELECT COUNT(*) FROM appointments
                       WHERE date = ? AND status = 'scheduled'
                         AND datetime(date || ' ' || time)
                             < datetime(date || ' ' || ?, '+' || ? || ' minutes')
                         AND datetime(date || ' ' || time, '+' || service_duration || ' minutes')
                             > datetime(date || ' ' || ?)
                    """,
                    (date, time, service_duration, time),
                )
            count = (await cursor.fetchone())[0]
            if count > 0:
                await db.execute("ROLLBACK")
                raise ValueError("Этот слот уже занят. Выберите другое время.")

            cursor = await db.execute(
                """INSERT INTO appointments
                   (user_id, name, phone, service_id, service_name, service_duration,
                    service_price, date, time, status, master_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', ?)""",
                (user_id, name, phone, service_id, service_name, service_duration,
                 service_price, date, time, master_id),
            )
            await db.execute("COMMIT")
            return cursor.lastrowid
        except ValueError:
            raise
        except Exception:
            await db.execute("ROLLBACK")
            raise


async def get_appointments_by_date_full(date: str) -> list[dict[str, Any]]:
    return await _dict_rows(
        """SELECT a.id, a.user_id, a.name, a.phone, a.service_name, a.service_duration,
                  a.service_price, a.date, a.time, a.status, a.client_cancelled,
                  a.master_id, m.name AS master_name
           FROM appointments a
           LEFT JOIN masters m ON m.id = a.master_id
           WHERE a.date = ?
           ORDER BY a.time""",
        (date,),
    )


async def get_appointment_by_id(appointment_id: int) -> dict[str, Any] | None:
    return await _dict_row(
        """SELECT a.*, m.name AS master_name
           FROM appointments a
           LEFT JOIN masters m ON m.id = a.master_id
           WHERE a.id = ?""",
        (appointment_id,),
    )


async def update_appointment_status(appointment_id: int, status: str) -> None:
    db = await get_db()
    lock = await get_write_lock()
    async with lock:
        await db.execute("BEGIN IMMEDIATE")
        try:
            if status == "cancelled":
                await db.execute(
                    "UPDATE appointments SET status = ?, confirmed = 0 WHERE id = ?",
                    (status, appointment_id)
                )
            else:
                await db.execute(
                    "UPDATE appointments SET status = ? WHERE id = ?",
                    (status, appointment_id)
                )
            await db.execute("COMMIT")
        except Exception:
            await db.execute("ROLLBACK")
            raise


async def reschedule_appointment(
    appointment_id: int,
    new_date: str,
    new_time: str,
    service_duration: int,
    master_id: int | None = None,
) -> None:
    """
    Атомарно переносит запись на новое время.
    Бросает ValueError если:
      • новый слот пересекается с другой записью,
      • новая дата — выходной (is_day_off / weekly_schedule / master_schedule),
      • новое время выходит за рабочие часы или попадает в blocked_slots.

    Defence-in-depth: хендлер уже фильтрует слоты через generate_free_slots,
    но подделка callback rs_time_<id>_<date>_<time> пройдёт guard и без проверки
    в БД-слое вылезет как "запись на закрытый день" → поход клиента в закрытый
    салон. БД — последняя линия.
    """
    # Импорты здесь, а не наверху: эти функции живут в db/settings.py и db/masters.py,
    # которые импортят из db.connection. Top-level — циклический импорт.
    from db.settings import get_day_schedule, is_day_off, get_time_blocks
    from db.masters import get_day_schedule_for_master, get_time_blocks_for_master

    # Парсинг времени — дешёвое и без БД, делаем до lock'а.
    try:
        hh, mm = new_time.split(":")
        slot_start_min = int(hh) * 60 + int(mm)
    except (ValueError, IndexError) as exc:
        raise ValueError("Некорректное время.") from exc
    slot_end_min = slot_start_min + service_duration

    db = await get_db()
    lock = await get_write_lock()
    async with lock:
        await db.execute("BEGIN IMMEDIATE")
        try:
            # Валидация внутри lock+BEGIN IMMEDIATE: иначе TOCTOU — админ может
            # поставить day_off между нашим чтением и UPDATE.
            if master_id is not None:
                day_sched = await get_day_schedule_for_master(master_id, new_date)
                if day_sched is None:
                    await db.execute("ROLLBACK")
                    raise ValueError("Этот день — выходной или заблокирован для мастера.")
                blocks = await get_time_blocks_for_master(master_id, new_date)
            else:
                if await is_day_off(new_date):
                    await db.execute("ROLLBACK")
                    raise ValueError("Этот день заблокирован.")
                day_sched = await get_day_schedule(new_date)
                if day_sched is None:
                    await db.execute("ROLLBACK")
                    raise ValueError("Салон не работает в этот день недели.")
                blocks = await get_time_blocks(new_date)

            work_start_h, work_end_h = day_sched
            if slot_start_min < work_start_h * 60 or slot_end_min > work_end_h * 60:
                await db.execute("ROLLBACK")
                raise ValueError("Время вне рабочих часов.")

            for b_start, b_end in blocks:
                try:
                    bh1, bm1 = b_start.split(":")
                    bh2, bm2 = b_end.split(":")
                except (ValueError, IndexError):
                    continue
                block_start_min = int(bh1) * 60 + int(bm1)
                block_end_min = int(bh2) * 60 + int(bm2)
                # Симметричный overlap с blocked-диапазоном.
                if slot_start_min < block_end_min and slot_end_min > block_start_min:
                    await db.execute("ROLLBACK")
                    raise ValueError("Время попадает в заблокированный диапазон.")
            # Проверка пересечения с другими scheduled записями (исключая саму переносимую).
            # Симметричный overlap: existing.start < new.end AND existing.end > new.start.
            if master_id is not None:
                cursor = await db.execute(
                    """SELECT COUNT(*) FROM appointments
                       WHERE date = ? AND master_id = ? AND status = 'scheduled'
                         AND id != ?
                         AND datetime(date || ' ' || time)
                             < datetime(date || ' ' || ?, '+' || ? || ' minutes')
                         AND datetime(date || ' ' || time, '+' || service_duration || ' minutes')
                             > datetime(date || ' ' || ?)
                    """,
                    (new_date, master_id, appointment_id, new_time, service_duration, new_time),
                )
            else:
                cursor = await db.execute(
                    """SELECT COUNT(*) FROM appointments
                       WHERE date = ? AND status = 'scheduled'
                         AND id != ?
                         AND datetime(date || ' ' || time)
                             < datetime(date || ' ' || ?, '+' || ? || ' minutes')
                         AND datetime(date || ' ' || time, '+' || service_duration || ' minutes')
                             > datetime(date || ' ' || ?)
                    """,
                    (new_date, appointment_id, new_time, service_duration, new_time),
                )
            count = (await cursor.fetchone())[0]
            if count > 0:
                await db.execute("ROLLBACK")
                raise ValueError("Этот слот уже занят. Выберите другое время.")

            await db.execute(
                "UPDATE appointments SET date = ?, time = ?, status = 'scheduled' WHERE id = ?",
                (new_date, new_time, appointment_id),
            )
            # Перенос = новый горизонт → старые маркеры reminder_24h/reminder_2h
            # больше не релевантны. Без DELETE клиент не получит напоминание,
            # если новое время попадает в уже «отправленное» окно.
            await db.execute(
                "DELETE FROM sent_reminders WHERE appointment_id = ?",
                (appointment_id,),
            )
            await db.execute("COMMIT")
        except ValueError:
            raise
        except Exception:
            await db.execute("ROLLBACK")
            raise


async def get_appointments_by_phone(phone: str) -> list[dict[str, Any]]:
    escaped = phone.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return await _dict_rows(
        """SELECT id, user_id, name, phone, service_name, date, time, status
           FROM appointments
           WHERE phone LIKE ? ESCAPE '\\'
           ORDER BY date DESC, time DESC""",
        (f"%{escaped}%",),
    )


async def get_upcoming_appointments() -> list[dict[str, Any]]:
    """
    Для планировщика напоминаний. Возвращает dict-строки —
    scheduler.py обращается по именам ключей, а не по позиции.

    date('now') в SQLite возвращает UTC, а appointments.date хранится
    в локальном TZ салона. В окне 00:00-05:00 Ташкент UTC-дата отстаёт
    на день → SQL включает вчерашние записи в выборку. Подставляем
    локальную дату явно.
    """
    today_local = now_local().strftime("%Y-%m-%d")
    return await _dict_rows(
        """SELECT id, user_id, name, service_name, date, time
           FROM appointments
           WHERE status = 'scheduled' AND date >= ?
           ORDER BY date, time""",
        (today_local,),
    )


async def get_client_appointments(user_id: int) -> list[dict[str, Any]]:
    """Все записи клиента (будущие + прошлые)."""
    return await _dict_rows(
        """SELECT id, service_id, service_name, service_price, service_duration,
                  date, time, status, client_cancelled
           FROM appointments
           WHERE user_id = ?
           ORDER BY date DESC, time DESC
           LIMIT 20""",
        (user_id,),
    )


async def cancel_appointment_by_client(
    appointment_id: int, user_id: int, reason: str = ""
) -> bool:
    """
    Клиент отменяет свою запись.
    Возвращает True если успешно, False если запись не найдена/не принадлежит клиенту.
    SELECT+UPDATE внутри BEGIN IMMEDIATE под write_lock — без этого
    параллельный UPDATE (напр. админский reschedule) мог пройти между
    нашими SELECT и UPDATE, и мы бы «отменили» уже переехавшую запись.
    """
    db = await get_db()
    lock = await get_write_lock()
    async with lock:
        await db.execute("BEGIN IMMEDIATE")
        try:
            cursor = await db.execute(
                "SELECT id, status FROM appointments WHERE id = ? AND user_id = ? AND status = 'scheduled'",
                (appointment_id, user_id)
            )
            row = await cursor.fetchone()
            if not row:
                await db.execute("ROLLBACK")
                return False

            await db.execute(
                "UPDATE appointments SET status = 'cancelled', confirmed = 0, client_cancelled = 1, cancel_reason = ? WHERE id = ?",
                (reason, appointment_id)
            )
            await db.execute("COMMIT")
            return True
        except Exception:
            await db.execute("ROLLBACK")
            raise


async def get_all_future_appointments() -> list[dict[str, Any]]:
    # date('now') = UTC; локальная дата подставляется явно, иначе в окне
    # 00:00-05:00 Ташкент вчерашние записи всплывают как «будущие».
    today_local = now_local().strftime("%Y-%m-%d")
    return await _dict_rows(
        """SELECT id, name, phone, service_name, date, time, status
           FROM appointments
           WHERE status = 'scheduled' AND date >= ?
           ORDER BY date, time""",
        (today_local,),
    )


async def get_stats() -> dict:
    db = await get_db()
    async def fetchone(sql, params=()):
        cur = await db.execute(sql, params)
        return await cur.fetchone()

    today = now_local().strftime("%Y-%m-%d")

    today_count = (await fetchone(
        "SELECT COUNT(*) FROM appointments WHERE date = ? AND status != 'cancelled'", (today,)
    ))[0]

    week_count = (await fetchone(
        """SELECT COUNT(*) FROM appointments
           WHERE strftime('%Y-%W', date) = strftime('%Y-%W', ?)
             AND status != 'cancelled'""", (today,)
    ))[0]

    month_count = (await fetchone(
        """SELECT COUNT(*) FROM appointments
           WHERE strftime('%Y-%m', date) = strftime('%Y-%m', ?)
             AND status != 'cancelled'""", (today,)
    ))[0]

    total_revenue = (await fetchone(
        "SELECT COALESCE(SUM(service_price), 0) FROM appointments WHERE status = 'completed'"
    ))[0]

    completed_count = (await fetchone(
        "SELECT COUNT(*) FROM appointments WHERE status = 'completed'"
    ))[0]

    cancelled_count = (await fetchone(
        "SELECT COUNT(*) FROM appointments WHERE status = 'cancelled'"
    ))[0]

    avg_check = (total_revenue / completed_count) if completed_count > 0 else 0

    # Возврат клиентов (уникальные user_id с > 1 записью)
    returning_row = await fetchone(
        """SELECT COUNT(*) FROM (
               SELECT user_id, COUNT(*) as cnt FROM appointments
               WHERE status = 'completed'
               GROUP BY user_id HAVING cnt > 1
           )"""
    )
    returning_clients = returning_row[0] if returning_row else 0

    # Конверсия: scheduled → completed за месяц
    month_scheduled = (await fetchone(
        """SELECT COUNT(*) FROM appointments
           WHERE strftime('%Y-%m', date) = strftime('%Y-%m', 'now')
             AND status IN ('scheduled', 'completed', 'no_show')"""
    ))[0]
    month_completed = (await fetchone(
        """SELECT COUNT(*) FROM appointments
           WHERE strftime('%Y-%m', date) = strftime('%Y-%m', 'now')
             AND status = 'completed'"""
    ))[0]
    conversion = (month_completed / month_scheduled * 100) if month_scheduled > 0 else 0

    top_row = await fetchone(
        """SELECT service_name, COUNT(*) as cnt FROM appointments
           WHERE status != 'cancelled'
           GROUP BY service_name ORDER BY cnt DESC LIMIT 1"""
    )
    top_service_name = top_row[0] if top_row else "—"
    top_service_count = top_row[1] if top_row else 0

    return {
        "today_count": today_count,
        "week_count": week_count,
        "month_count": month_count,
        "total_revenue": total_revenue,
        "top_service_name": top_service_name,
        "top_service_count": top_service_count,
        "completed_count": completed_count,
        "cancelled_count": cancelled_count,
        "avg_check": avg_check,
        "returning_clients": returning_clients,
        "conversion": conversion,
    }


async def get_stats_by_master() -> list[dict[str, Any]]:
    """Статистика по каждому мастеру: записи, выручка, рейтинг."""
    return await _dict_rows(
        """SELECT m.id, m.name,
                  COUNT(CASE WHEN a.status = 'completed' THEN 1 END) AS completed,
                  COUNT(CASE WHEN a.status = 'scheduled' THEN 1 END) AS scheduled,
                  COUNT(CASE WHEN a.status = 'cancelled' THEN 1 END) AS cancelled,
                  COALESCE(SUM(CASE WHEN a.status = 'completed' THEN a.service_price END), 0) AS revenue,
                  ROUND(AVG(CASE WHEN r.rating IS NOT NULL THEN r.rating END), 1) AS avg_rating,
                  COUNT(r.id) AS reviews_count
           FROM masters m
           LEFT JOIN appointments a ON a.master_id = m.id
           LEFT JOIN reviews r ON r.appointment_id = a.id
           WHERE m.is_active = 1
           GROUP BY m.id
           ORDER BY revenue DESC"""
    )


async def get_appointments_for_export(period: str) -> list[dict[str, Any]]:
    """
    Выборка записей для экспорта.
    period: 'today' | 'week' | 'month' | 'all'
    """
    filters = {
        "today": "WHERE date = date('now')",
        "week":  "WHERE strftime('%Y-%W', date) = strftime('%Y-%W', 'now')",
        "month": "WHERE strftime('%Y-%m', date) = strftime('%Y-%m', 'now')",
        "all":   "",
    }
    where = filters.get(period, "")
    return await _dict_rows(
        f"""SELECT date, time, name, phone, service_name, service_price, status
            FROM appointments
            {where}
            ORDER BY date DESC, time DESC"""
    )


async def get_user_appointments_page(user_id: int, page: int = 0, per_page: int = 5) -> list[dict[str, Any]]:
    """Получает страницу записей пользователя, ORDER BY date DESC, time DESC."""
    offset = page * per_page
    return await _dict_rows(
        """SELECT id, service_id, service_name, service_price, service_duration,
                  date, time, status, client_cancelled
           FROM appointments
           WHERE user_id = ?
           ORDER BY date DESC, time DESC
           LIMIT ? OFFSET ?""",
        (user_id, per_page, offset),
    )


async def count_user_appointments(user_id: int) -> int:
    """Общее количество записей пользователя."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT COUNT(*) FROM appointments WHERE user_id = ?",
        (user_id,),
    )
    return (await cursor.fetchone())[0]


async def get_user_appointments_full(user_id: int, limit: int = 30) -> list[dict[str, Any]]:
    """
    Получает последние N записей клиента со всем, что нужно для B-рендера
    «Мои записи»: платёжные поля, длительность, имя мастера через LEFT JOIN.

    Отдельная функция от get_user_appointments_page, потому что тот SELECT
    не тянет paid_at/master_name/payment_* — добавлять туда эти поля сломало
    бы форму её результата (исторически короткая). Здесь один запрос вместо
    отдельного get_master на каждую запись.

    ORDER BY date DESC, time DESC — свежие первыми. Вызывающий сам разделит
    на upcoming (status='scheduled' AND date>=today) и past.
    """
    return await _dict_rows(
        """SELECT a.id, a.service_id, a.service_name, a.service_price,
                  a.service_duration, a.date, a.time, a.status,
                  a.client_cancelled, a.paid_at, a.payment_provider,
                  a.payment_invoice_id, a.payment_pay_url,
                  a.master_id, a.phone, m.name AS master_name
           FROM appointments a
           LEFT JOIN masters m ON m.id = a.master_id
           WHERE a.user_id = ?
           ORDER BY a.date DESC, a.time DESC
           LIMIT ?""",
        (user_id, limit),
    )


async def save_appointment_addons(appointment_id: int, addon_ids: list[int]) -> None:
    """Сохраняет выбранные аддоны с текущими ценами из service_addons.
    Весь блок (SELECT цен + INSERT аддонов) внутри одной транзакции, иначе
    админ может поменять цену аддона между нашими SELECT и INSERT, а также
    параллельный commit() сфлашит наш первый INSERT без второго.
    """
    if not addon_ids:
        return
    db = await get_db()
    lock = await get_write_lock()
    async with lock:
        await db.execute("BEGIN IMMEDIATE")
        try:
            for addon_id in addon_ids:
                # Берём актуальную цену аддона на момент записи
                cursor = await db.execute(
                    "SELECT price FROM service_addons WHERE id = ? AND is_active = 1",
                    (addon_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    continue
                price = row[0]
                await db.execute(
                    "INSERT OR IGNORE INTO appointment_addons (appointment_id, addon_id, price) VALUES (?, ?, ?)",
                    (appointment_id, addon_id, price),
                )
            await db.execute("COMMIT")
        except Exception:
            await db.execute("ROLLBACK")
            raise
