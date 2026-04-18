import asyncio
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, ADMIN_IDS, REDIS_URL
from db import init_db, close_db
from handlers import client, admin
from handlers import admin_appointments, admin_clients, admin_services
from handlers import admin_stats, admin_settings, admin_blocks, admin_manage
from handlers import reviews, admin_export, admin_masters
from handlers import client_reminders, client_history
from scheduler import setup_scheduler
from utils.admin import refresh_admins_cache
from utils.panel import set_reply_kb
from keyboards.inline import admin_reply_keyboard


async def _build_storage() -> BaseStorage:
    """
    Выбирает FSM-storage: Redis при заданном REDIS_URL и успешном ping,
    иначе MemoryStorage. Любая ошибка Redis → warning + fallback, бот не падает.
    """
    if not REDIS_URL:
        logger.info("REDIS_URL не задан → MemoryStorage (FSM теряется при рестарте)")
        return MemoryStorage()
    try:
        # Локальные импорты: redis — опциональная зависимость на этапе Phase 1.
        from aiogram.fsm.storage.redis import RedisStorage
        from redis.asyncio import Redis

        client = Redis.from_url(REDIS_URL)
        await client.ping()
        logger.info("FSM storage: RedisStorage (%s)", REDIS_URL)
        return RedisStorage(redis=client)
    except Exception as exc:
        # Redis лёг или URL кривой — логируем и работаем без персиста.
        logger.warning(
            "Redis недоступен (%s): %s → fallback на MemoryStorage", REDIS_URL, exc
        )
        return MemoryStorage()


async def main() -> None:
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=await _build_storage())

    # Админские роутеры регистрируются ПЕРЕД клиентским,
    # чтобы catch-all fallback_message не перехватил их сообщения
    dp.include_router(admin.router)
    dp.include_router(admin_appointments.router)
    dp.include_router(admin_clients.router)
    dp.include_router(admin_services.router)
    dp.include_router(admin_stats.router)
    dp.include_router(admin_settings.router)
    dp.include_router(admin_blocks.router)
    dp.include_router(admin_manage.router)
    dp.include_router(admin_masters.router)
    dp.include_router(admin_export.router)
    dp.include_router(reviews.router)  # до client.router — чтобы rev_* callbacks не попали в fallback
    # client_reminders и client_history — ДО client.router, т.к. client содержит
    # catch-all fallback_message. Порядок внутри этой тройки неважен (у них нет пересечений),
    # кроме того, что конкретные F-фильтры должны предшествовать catch-all message().
    dp.include_router(client_reminders.router)
    dp.include_router(client_history.router)
    dp.include_router(client.router)

    await init_db()
    await refresh_admins_cache()

    # Запоминаем reply keyboard для админ-чатов
    for admin_id in ADMIN_IDS:
        set_reply_kb(admin_id, admin_reply_keyboard())

    scheduler = setup_scheduler(bot)
    scheduler.start()

    logger.info("Бот запущен")

    try:
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        logger.info("Polling cancelled, shutting down")
    finally:
        logger.info("Бот останавливается.")
        scheduler.shutdown()
        await close_db()
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
