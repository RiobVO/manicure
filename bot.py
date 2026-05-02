import asyncio
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, ADMIN_IDS
from db import init_db, close_db
from handlers import client, admin
from handlers import admin_appointments, admin_clients, admin_services
from handlers import admin_stats, admin_settings, admin_blocks, admin_manage
from handlers import reviews, admin_export, admin_masters
from handlers import client_reminders, client_history
from scheduler import setup_scheduler
from middlewares.fsm_guard import FSMGuardMiddleware
from utils.admin import refresh_admins_cache
from utils.panel import set_reply_kb
from keyboards.inline import admin_reply_keyboard


async def main() -> None:
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    # Один инстанс на оба типа — иначе UUID session-маркера расходится
    _fsm_guard = FSMGuardMiddleware()
    dp.message.middleware(_fsm_guard)
    dp.callback_query.middleware(_fsm_guard)

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
        logger.info("Бот останавливается. Активные FSM-сессии будут сброшены при следующем запуске (FSMGuardMiddleware).")
        scheduler.shutdown()
        await close_db()
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
