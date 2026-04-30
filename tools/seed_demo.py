"""
tools/seed_demo.py — наполняет демо-БД «живыми» данными для питча салонам.

ЗАЧЕМ: свежий бот после install.sh показывает «Сегодня: 0 записей · 0 сум».
Демонстрировать на нём бессмысленно — владелица не представит свой салон в
пустой коробке. Этот скрипт делает так, чтобы любой экран (Сегодня, Календарь,
Статистика, Источники, Мастера, Отзывы) выглядел как у работающего салона.

ЧТО НАСЫПАЕТ:
  • 8 услуг (маникюр/педикюр/наращивание/SPA) с реальными ценами Ташкента,
    включая аддоны (дизайн, втирка, френч).
  • 3 мастера с разными bio и стажем, расписание копируется из weekly_schedule.
  • 5 источников трафика (3 дефолтных + Instagram + Рекомендация).
  • ~30 фейковых клиентов с распределением по источникам и языкам (80/20 ru/uz).
  • ~70 записей: 14 дней назад → завтра+13 дней. 80% completed, 10% cancelled,
    10% no_show в прошлом; всё scheduled в будущем.
  • ~12 отзывов с реалистичным распределением рейтингов (60% 5★, 30% 4★).

ЗАПУСК:
    python tools/seed_demo.py --reset

ФЛАГИ:
  --reset  — стереть все user-данные перед сидом (services/masters/appts/...).
             БЕЗ него скрипт ругается, если в БД уже что-то есть.
  --force  — пропустить проверку TENANT_SLUG (для случаев когда демо-инстанс
             назван не из стандартного whitelist).

ВАЖНО:
  • Скрипт работает с DB_PATH из config (читает .env). Бот должен быть
    остановлен (`docker compose stop bot`) — иначе SQLite-WAL может
    конфликтовать.
  • TENANT_SLUG проверяется по whitelist (см. DEMO_SLUGS) для защиты от
    случайного запуска на боевом инстансе.
  • random.seed зафиксирован — повторный прогон с --reset даёт ту же картину
    (стабильность для скриншотов и видео-демо).
"""
from __future__ import annotations

import argparse
import asyncio
import random
import sys
from datetime import timedelta
from pathlib import Path

# Корень проекта в sys.path — чтобы скрипт можно было звать как
# `python tools/seed_demo.py` из корня без PYTHONPATH-шаманства.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import DB_PATH, TENANT_SLUG  # noqa: E402
from db.connection import close_db, get_db, init_db  # noqa: E402
from db.masters import create_master  # noqa: E402
from utils.timezone import now_local  # noqa: E402

# ─── Whitelist демо-инстансов ────────────────────────────────────────────────
# Если TENANT_SLUG не в этом множестве — скрипт отказывается работать без
# --force. Защита уровня reset_demo.sh: лучше ругаться, чем стереть прод.
DEMO_SLUGS: frozenset[str] = frozenset({
    "demo", "demo-nails", "manicure-demo", "test", "sabina-nails",
})

# ─── Каталог: услуги ─────────────────────────────────────────────────────────
# Кортеж: (name, price_uzs, duration_min, category, weight)
# weight — вес для случайной выборки. Хиты («гель-лак») чаще, редкие
# (наращивание) реже. Сумма весов не обязана быть 100.
SERVICES: list[tuple[str, int, int, str, int]] = [
    # Маникюр / педикюр — основной поток, высокие веса.
    ("Маникюр классический",       80_000,  45,  "hands", 8),
    ("Маникюр + покрытие лаком",   120_000, 60,  "hands", 6),
    ("Маникюр + гель-лак",         180_000, 90,  "hands", 15),
    ("Наращивание ногтей",         350_000, 150, "hands", 3),
    ("Снятие покрытия",            50_000,  30,  "hands", 4),
    ("Педикюр классический",       150_000, 60,  "feet",  6),
    ("Педикюр + гель-лак",         220_000, 90,  "feet",  8),
    ("SPA-педикюр",                280_000, 120, "feet",  4),

    # Лицо — депиляция лицевых зон, средняя популярность.
    ("Брови",                      50_000,  20, "face",  5),
    ("Усики",                      30_000,  15, "face",  3),
    ("Лицо полностью",             80_000,  30, "face",  2),

    # Воск — топовые зоны (без подмышек, см. CLAUDE.md / архитектуру).
    ("Руки до локтя",              60_000,  30, "wax",   3),
    ("Ноги полностью",             200_000, 60, "wax",   4),
    ("Бикини классическое",        150_000, 45, "wax",   2),

    # Шугаринг — те же зоны + подмышки.
    ("Ноги полностью",             220_000, 60, "sugar", 5),
    ("Подмышки",                   70_000,  20, "sugar", 4),
    ("Бикини глубокое",            280_000, 50, "sugar", 3),

    # Уходовые процедуры — низкая частота, высокий чек.
    ("Ультразвуковая чистка",      250_000, 60, "care",  3),
    ("Механическая чистка",        200_000, 75, "care",  2),
]

# Аддоны: (service_name, addon_name, addon_price). Цепляются к 2 хитам.
ADDONS: list[tuple[str, str, int]] = [
    ("Маникюр + гель-лак", "Дизайн (1 палец)", 20_000),
    ("Маникюр + гель-лак", "Втирка / блёстки", 15_000),
    ("Маникюр + гель-лак", "Френч",            25_000),
    ("Педикюр + гель-лак", "Дизайн",           20_000),
]

# ─── Каталог: мастера ────────────────────────────────────────────────────────
MASTERS: list[dict[str, str]] = [
    {"name": "Алия Хасанова",   "bio": "6 лет опыта · гель-лак · nail-art"},
    {"name": "Севара Каримова", "bio": "4 года · классика и педикюр"},
    {"name": "Камилла Юсупова", "bio": "3 года · художественная роспись"},
]

# Источники трафика поверх дефолтных desk/mirror/door (приходят из миграции).
EXTRA_SOURCES: list[tuple[str, str]] = [
    ("instagram", "Instagram"),
    ("recommend", "Рекомендация"),
]

# Имена клиентов: микс узбекских и русскоязычных. Соответствует реальности
# Ташкента, добавляет визуальное разнообразие в списках «Клиенты», «Сегодня».
CLIENT_NAMES: list[str] = [
    "Малика", "Дилноза", "Феруза", "Шахноза", "Гулнора", "Мадина",
    "Зухра", "Нилуфар", "Севара", "Камила", "Лола", "Зарина",
    "Азиза", "Ирода", "Динара", "Нодира", "Шахло", "Гульчехра",
    "Замира", "Эльвира",
    "Виктория", "Анастасия", "Юлия", "Ирина", "Ольга",
    "Светлана", "Дарья", "Екатерина", "Татьяна", "Алина",
]

# Реалистичные шаблоны отзывов. Половина записей идёт без комментария
# (только рейтинг) — так оно и в жизни.
REVIEW_COMMENTS: list[str] = [
    "Спасибо, всё отлично!",
    "Очень довольна, мастер супер.",
    "Лучший маникюр в городе.",
    "Аккуратно, быстро, рекомендую.",
    "Девочки умницы, приду ещё.",
    "Чисто, уютно, мастер внимательная.",
    "Покрытие держится отлично уже 2 недели.",
    "Дизайн получился даже лучше, чем на фото.",
    "Спасибо! Буду советовать подругам.",
    "Всё на высшем уровне.",
]

# Детерминированный seed: одна и та же команда даёт одну и ту же картинку.
# Критично для скриншотов и видео-демо — иначе каждый ре-сид рандомит цифры.
random.seed(42)


# ─── Утилиты ────────────────────────────────────────────────────────────────

def _phone() -> str:
    """Фейковый узбекский номер вида +998 9X XXXXXXX. Не валидируется ботом."""
    return f"+998 9{random.randint(0, 9)} {random.randint(1_000_000, 9_999_999)}"


def _time_str(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h:02d}:{m:02d}"


def _to_min(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def _weighted_pick_service() -> tuple[str, int, int, str, int]:
    """Выбрать услугу с учётом веса популярности."""
    weights = [s[4] for s in SERVICES]
    return random.choices(SERVICES, weights=weights, k=1)[0]


def _slot_fits(busy: list[tuple[int, int]], start_min: int, dur_min: int) -> bool:
    """Проверка пересечения нового слота со списком занятых на мастере.
    busy — список (start_min, end_min). Без этой проверки в одном дне у одного
    мастера накапливаются перекрывающиеся записи и календарь визуально лажает."""
    end_min = start_min + dur_min
    for bs, be in busy:
        if start_min < be and end_min > bs:
            return False
    return True


# ─── Шаги сида ──────────────────────────────────────────────────────────────

async def wipe() -> None:
    """Удаляет все user-данные. Не трогает weekly_schedule, traffic_sources,
    settings, sqlite_master/PRAGMA — они должны выжить как «инфраструктура»."""
    db = await get_db()
    # Порядок DELETE важен из-за FK ON DELETE CASCADE: дочерние перед родителями.
    tables = [
        "appointment_addons",
        "service_addons",
        "reviews",
        "sent_reminders",
        "appointments",
        "blocked_slots",
        "master_schedule",
        "masters",
        "client_profiles",
        "admin_logs",
        "admins",
        "services",
    ]
    for table in tables:
        await db.execute(f"DELETE FROM {table}")
    # Сбрасываем AUTOINCREMENT — иначе ID растут до бесконечности при повторных
    # прогонах, и одни и те же записи каждый раз получают новые id.
    await db.execute(
        "DELETE FROM sqlite_sequence WHERE name IN ("
        "'appointments','services','masters','reviews','appointment_addons',"
        "'service_addons','sent_reminders','admin_logs','blocked_slots'"
        ")"
    )
    await db.commit()


async def seed_services() -> dict[str, tuple[int, int, int]]:
    """Засеять услуги и аддоны. Возвращает {name: (id, price, duration)}."""
    db = await get_db()
    name_to_meta: dict[str, tuple[int, int, int]] = {}
    for i, (name, price, duration, category, _w) in enumerate(SERVICES):
        cur = await db.execute(
            "INSERT INTO services "
            "(name, price, duration, is_active, sort_order, category) "
            "VALUES (?, ?, ?, 1, ?, ?)",
            (name, price, duration, i, category),
        )
        name_to_meta[name] = (cur.lastrowid, price, duration)
    for service_name, addon_name, addon_price in ADDONS:
        sid, _, _ = name_to_meta[service_name]
        await db.execute(
            "INSERT INTO service_addons "
            "(service_id, name, price, is_active, sort_order) "
            "VALUES (?, ?, ?, 1, 0)",
            (sid, addon_name, addon_price),
        )
    await db.commit()
    return name_to_meta


async def seed_masters() -> list[int]:
    """Создаёт мастеров. create_master сам копирует weekly_schedule в
    master_schedule — нам не надо дублировать логику."""
    ids: list[int] = []
    db = await get_db()
    for i, m in enumerate(MASTERS):
        master_id = await create_master(user_id=None, name=m["name"], bio=m["bio"])
        await db.execute(
            "UPDATE masters SET sort_order = ? WHERE id = ?",
            (i, master_id),
        )
        ids.append(master_id)
    await db.commit()
    return ids


async def seed_traffic_sources() -> None:
    """Дефолтные desk/mirror/door приходят из миграции v4→v5. Доливаем
    Instagram и Рекомендацию, чтобы экран «Источники» выглядел разнообразнее."""
    db = await get_db()
    for code, label in EXTRA_SOURCES:
        await db.execute(
            "INSERT OR IGNORE INTO traffic_sources (code, label) VALUES (?, ?)",
            (code, label),
        )
    await db.commit()


async def seed_clients(count: int = 30) -> list[dict]:
    """Создаёт фейковые client_profiles. user_id берём от 900_000_000+, чтобы
    ни в каком случае не пересекаться с реальными Telegram-id (там до ~7 знаков
    у старых юзеров и ~10 у новых)."""
    db = await get_db()
    cur = await db.execute("SELECT code FROM traffic_sources")
    sources = [r[0] for r in await cur.fetchall()]

    clients: list[dict] = []
    for i in range(count):
        base_name = CLIENT_NAMES[i % len(CLIENT_NAMES)]
        # Если клиентов больше, чем имён — добавляем суффикс «Малика 2».
        name = base_name if i < len(CLIENT_NAMES) else f"{base_name} {i // len(CLIENT_NAMES) + 1}"
        user_id = 900_000_000 + i
        phone = _phone()
        source = random.choice(sources) if sources else None
        lang = "uz" if random.random() < 0.2 else "ru"
        await db.execute(
            "INSERT OR REPLACE INTO client_profiles "
            "(user_id, name, phone, source, lang) VALUES (?, ?, ?, ?, ?)",
            (user_id, name, phone, source, lang),
        )
        clients.append({"user_id": user_id, "name": name, "phone": phone})
    await db.commit()
    return clients


async def seed_appointments(
    services_meta: dict[str, tuple[int, int, int]],
    master_ids: list[int],
    clients: list[dict],
) -> tuple[list[int], int]:
    """
    Раскидывает записи: 14 дней назад → +14 дней вперёд.

    Возвращает (completed_past_ids, total_count) — completed-id нужны для
    последующего сидинга отзывов (отзыв можно оставить только на выполненную
    запись, бизнес-логика).
    """
    db = await get_db()
    today = now_local().date()

    # Слоты: рабочий день 09:00–19:00, шаг 30 минут.
    slot_starts = list(range(9 * 60, 19 * 60, 30))

    completed_past: list[int] = []
    total = 0

    # Прошлое: дни от -14 до -1 включительно.
    # 3-5 записей в день, статус 80/10/10 completed/cancelled/no_show.
    for day_offset in range(-14, 0):
        date_str = (today + timedelta(days=day_offset)).strftime("%Y-%m-%d")
        per_master_busy: dict[int, list[tuple[int, int]]] = {
            mid: [] for mid in master_ids
        }
        for _ in range(random.randint(3, 5)):
            master_id = random.choice(master_ids)
            client = random.choice(clients)
            svc_name, price, duration, _cat, _w = _weighted_pick_service()
            sid, _, _ = services_meta[svc_name]
            placed = False
            for _try in range(8):
                start = random.choice(slot_starts)
                if _slot_fits(per_master_busy[master_id], start, duration):
                    per_master_busy[master_id].append((start, start + duration))
                    placed = True
                    break
            if not placed:
                continue
            roll = random.random()
            if roll < 0.80:
                status = "completed"
            elif roll < 0.90:
                status = "cancelled"
            else:
                status = "no_show"
            cur = await db.execute(
                "INSERT INTO appointments "
                "(user_id, name, phone, service_id, service_name, "
                " service_duration, service_price, date, time, status, "
                " master_id, confirmed) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                (client["user_id"], client["name"], client["phone"],
                 sid, svc_name, duration, price, date_str, _time_str(start),
                 status, master_id),
            )
            appt_id = cur.lastrowid
            total += 1
            if status == "completed":
                completed_past.append(appt_id)

    # Будущее: сегодня + 13 дней вперёд.
    # Сегодня — насыщенный (5-7 записей), дальше — реже.
    for day_offset in range(0, 14):
        date_str = (today + timedelta(days=day_offset)).strftime("%Y-%m-%d")
        n = random.randint(5, 7) if day_offset == 0 else random.randint(1, 3)
        per_master_busy = {mid: [] for mid in master_ids}
        for _ in range(n):
            master_id = random.choice(master_ids)
            client = random.choice(clients)
            svc_name, price, duration, _cat, _w = _weighted_pick_service()
            sid, _, _ = services_meta[svc_name]
            placed = False
            for _try in range(8):
                start = random.choice(slot_starts)
                if _slot_fits(per_master_busy[master_id], start, duration):
                    per_master_busy[master_id].append((start, start + duration))
                    placed = True
                    break
            if not placed:
                continue
            await db.execute(
                "INSERT INTO appointments "
                "(user_id, name, phone, service_id, service_name, "
                " service_duration, service_price, date, time, status, "
                " master_id, confirmed) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                (client["user_id"], client["name"], client["phone"],
                 sid, svc_name, duration, price, date_str, _time_str(start),
                 "scheduled", master_id),
            )
            total += 1

    await db.commit()
    return completed_past, total


async def seed_reviews(completed_ids: list[int]) -> int:
    """Отзыв оставляет ~50% выполненных клиентов. Распределение рейтингов
    реалистичное: 5★ — 60%, 4★ — 30%, 3★ — 8%, 2★ — 2%."""
    if not completed_ids:
        return 0
    db = await get_db()
    sample_size = max(1, len(completed_ids) // 2)
    sample = random.sample(completed_ids, k=sample_size)
    written = 0
    for appt_id in sample:
        roll = random.random()
        if roll < 0.60:
            rating = 5
        elif roll < 0.90:
            rating = 4
        elif roll < 0.98:
            rating = 3
        else:
            rating = 2
        comment = random.choice(REVIEW_COMMENTS) if random.random() < 0.5 else ""
        cur = await db.execute(
            "SELECT user_id FROM appointments WHERE id = ?", (appt_id,)
        )
        row = await cur.fetchone()
        if not row:
            continue
        await db.execute(
            "INSERT OR IGNORE INTO reviews "
            "(appointment_id, user_id, rating, comment) VALUES (?, ?, ?, ?)",
            (appt_id, row[0], rating, comment),
        )
        written += 1
    await db.commit()
    return written


# ─── main ───────────────────────────────────────────────────────────────────

async def _print_summary() -> None:
    """Финальный отчёт: что увидит владелица в админке после сида."""
    db = await get_db()

    cur = await db.execute(
        "SELECT COUNT(*), COALESCE(SUM(service_price), 0) "
        "FROM appointments WHERE status='completed'"
    )
    done, revenue = await cur.fetchone()

    cur = await db.execute(
        "SELECT COUNT(*) FROM appointments "
        "WHERE date = date('now', 'localtime') AND status='scheduled'"
    )
    today_count = (await cur.fetchone())[0]

    cur = await db.execute(
        "SELECT COUNT(*) FROM appointments WHERE status='scheduled'"
    )
    upcoming = (await cur.fetchone())[0]

    cur = await db.execute(
        "SELECT ROUND(AVG(rating), 2), COUNT(*) FROM reviews"
    )
    avg, total_rev = await cur.fetchone()

    print("")
    print("╔══════════════════════════════════════════════╗")
    print("║  ДЕМО ГОТОВО                                  ║")
    print("╚══════════════════════════════════════════════╝")
    print(f"  Сегодня:        {today_count} записей")
    print(f"  Всего грядущих: {upcoming}")
    print(f"  Выполнено:      {done} (выручка ≈ {revenue:,} сум)")
    print(f"  Отзывов:        {total_rev} (средний {avg or 0})")
    print("")
    print("  Запусти бота, /start от админа — открой «📊 Статистика».")


async def main_async(reset: bool, force: bool) -> int:
    if not force and TENANT_SLUG not in DEMO_SLUGS:
        print(f"⚠ TENANT_SLUG='{TENANT_SLUG}' не в демо-whitelist {sorted(DEMO_SLUGS)}.")
        print("  Если это действительно демо — добавь slug в DEMO_SLUGS этого скрипта.")
        print("  Если это БОЕВОЙ бот — НЕ ЗАПУСКАЙ, скрипт сотрёт реальные данные.")
        print("  Принудительный запуск: --force")
        return 2

    print(f"→ TENANT_SLUG = {TENANT_SLUG}")
    print(f"→ DB_PATH     = {DB_PATH}")

    # init_db создаст схему и наполнит дефолтными services/weekly_schedule/
    # traffic_sources, если БД совсем свежая. Это ок: wipe потом снесёт services
    # (наши перезатрут), а weekly_schedule/traffic_sources останутся.
    await init_db()

    db = await get_db()
    cur = await db.execute("SELECT COUNT(*) FROM appointments")
    existing = (await cur.fetchone())[0]

    if existing > 0:
        if not reset:
            print(f"⚠ В БД уже {existing} записей. Запусти с --reset чтобы перезаписать.")
            return 3
        print(f"→ В БД {existing} записей — стираю всё (--reset)...")
        await wipe()
    elif reset:
        # Идемпотентно: --reset на чистой БД ничего не ломает.
        print("→ БД пустая, --reset проигнорирован (нечего стирать).")

    print("→ Услуги...")
    services_meta = await seed_services()
    print(f"  {len(services_meta)} услуг + {len(ADDONS)} аддонов")

    print("→ Мастера...")
    master_ids = await seed_masters()
    print(f"  {len(master_ids)} с расписанием")

    print("→ Источники трафика...")
    await seed_traffic_sources()

    print("→ Клиенты...")
    clients = await seed_clients(count=30)
    print(f"  {len(clients)} профилей")

    print("→ Записи...")
    completed_ids, total = await seed_appointments(services_meta, master_ids, clients)
    print(f"  {total} всего, {len(completed_ids)} выполнено (база для отзывов)")

    print("→ Отзывы...")
    written = await seed_reviews(completed_ids)
    print(f"  {written} отзывов")

    await _print_summary()
    await close_db()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Наполняет демо-БД реалистичными данными для питча.",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="Стереть существующие данные перед сидом.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Пропустить проверку TENANT_SLUG (для не-стандартных демо-slug).",
    )
    args = parser.parse_args()
    return asyncio.run(main_async(reset=args.reset, force=args.force))


if __name__ == "__main__":
    sys.exit(main())
