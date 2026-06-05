"""
tools/seed_v4_categories.py — добавить новые услуги (face/depil/skincare/dental)
в существующий инстанс бота.

ЗАЧЕМ: при первом запуске нового инстанса db/seed.py наливает все 32 услуги
(6 старых + 26 новых из v.5). Но у уже задеплоенных салонов таблица services
не пуста, и блок «if COUNT(*) == 0» в init_db пропускается. Чтобы обновлённый
бот показал клиенту 6 категорий, в существующую БД надо доложить новые услуги
руками. Этот скрипт это и делает — идемпотентно.

ЧТО ДЕЛАЕТ:
  • Для каждой услуги из db/seed.py с category in {'face','depil','skincare','dental'}:
    — если в services уже есть строка с тем же name — пропускает (idempotent),
    — иначе INSERT с is_active=0, price=0.
  • НЕ трогает существующие услуги (включая hands/feet) — историю записей
    и цены салона мы не переписываем.
  • НЕ удаляет ничего.

ЗАПУСК (на VPS салона):
    docker compose exec bot python tools/seed_v4_categories.py

Повторный запуск ничего не меняет (отчёт «0 добавлено, N пропущено»).

После запуска: владелец заходит в админку → Услуги → видит новые услуги
помеченными 🔴 (неактивные), проставляет цены/длительность и активирует
по мере готовности.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db.connection import get_db, init_db, close_db, get_write_lock
from db.seed import SERVICES

# Категории, добавленные в v.5+ (после реструктуризации заказчицы).
# Старые (hands/feet) трогать не надо — у салона уже есть свой набор
# маникюрных/педикюрных услуг с реальными ценами.
NEW_CATEGORIES = {"face", "wax", "sugar", "care"}


async def main() -> int:
    await init_db()  # на всякий случай прогоняем миграции (v7→v8)
    db = await get_db()
    lock = await get_write_lock()

    new_services = [s for s in SERVICES if s.get("category") in NEW_CATEGORIES]
    added = 0
    skipped = 0

    async with lock:
        await db.execute("BEGIN IMMEDIATE")
        try:
            # sort_order: продолжаем с конца существующего списка, чтобы новые
            # услуги встали ниже маникюрных/педикюрных в админском списке.
            cursor = await db.execute("SELECT COALESCE(MAX(sort_order), 0) FROM services")
            base_sort = (await cursor.fetchone())[0]
            offset = 1
            for s in new_services:
                # Проверка дубля по name — у services нет UNIQUE-индекса, делаем руками.
                cur = await db.execute(
                    "SELECT id FROM services WHERE name = ?", (s["name"],)
                )
                if await cur.fetchone():
                    skipped += 1
                    continue
                await db.execute(
                    """INSERT INTO services (name, price, duration, is_active,
                                             sort_order, category, description, photo_file_id)
                       VALUES (?, ?, ?, ?, ?, ?, '', '')""",
                    (
                        s["name"],
                        int(s.get("price", 0)),
                        int(s.get("duration", 30)),
                        int(s.get("is_active", 0)),
                        base_sort + offset,
                        s["category"],
                    ),
                )
                added += 1
                offset += 1
            await db.execute("COMMIT")
        except Exception:
            await db.execute("ROLLBACK")
            raise

    print(f"seed_v4_categories: добавлено {added}, пропущено {skipped} "
          f"(уже было) из {len(new_services)} в наборе.")
    await close_db()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
