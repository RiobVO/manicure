import asyncio
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, ErrorEvent

from config import (
    ADMIN_IDS,
    BOT_TOKEN,
    LICENSE_CONTACT,
    LICENSE_KEY,
    REDIS_URL,
    TENANT_SLUG,
)
from db import init_db, close_db
from handlers import client, admin
from handlers import admin_appointments, admin_clients, admin_services
from handlers import admin_stats, admin_settings, admin_blocks, admin_manage
from handlers import reviews, admin_export, admin_masters, admin_master_schedule
from handlers import client_reminders, client_history, admin_status, admin_traffic
from handlers import master
from middlewares.license_gate import LicenseGateMiddleware
from scheduler import setup_scheduler
from utils.admin import all_admin_ids, refresh_admins_cache, refresh_masters_cache
from utils.error_reporter import mark_started, report_error
from utils.license import GRACE_DAYS, LicenseMode, evaluate_license
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
        # TTL=24ч на state и data: брошенные booking-флоу не копятся в Redis вечно.
        # Каждое действие пользователя обновляет expiry, активные не теряются.
        return RedisStorage(redis=client, state_ttl=86400, data_ttl=86400)
    except Exception as exc:
        # Redis лёг или URL кривой — логируем и работаем без персиста.
        logger.warning(
            "Redis недоступен (%s): %s → fallback на MemoryStorage", REDIS_URL, exc
        )
        return MemoryStorage()


async def _warn_grace(bot: Bot, license_state) -> None:
    """На старте в GRACE-режиме напоминаем админам что пора продлевать."""
    if license_state.license is None:
        return
    # GRACE_DAYS — единственный источник правды (utils/license.py). Не дублируем константу.
    grace_end = license_state.license.expires_at + timedelta(days=GRACE_DAYS)
    days_left = (grace_end - datetime.now(timezone.utc)).days
    text = (
        f"⚠ <b>Лицензия бота истекла</b>\n\n"
        f"Grace-режим. До блокировки: <b>{max(days_left, 0)} дн.</b>\n"
        f"Для продления обратитесь к {LICENSE_CONTACT}."
    )
    # DB-админы тоже должны получить warning; кеш прогрет через refresh_admins_cache() до вызова.
    for admin_id in all_admin_ids():
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception as exc:
            logger.warning("не доставил grace-предупреждение admin=%s: %s", admin_id, exc)


async def main() -> None:
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=await _build_storage())

    # Лицензия проверяется ДО любого хендлера. Enforcement (middleware-гейт)
    # включён: в RESTRICTED режиме бот отвечает только на /start с текстом про
    # истечение лицензии и контактом LICENSE_CONTACT. DEV/OK/GRACE — всё работает.
    license_state = evaluate_license(LICENSE_KEY, TENANT_SLUG)
    logger.info(
        "License mode=%s %s",
        license_state.mode.value,
        f"({license_state.reason})" if license_state.reason else "",
    )

    gate = LicenseGateMiddleware(license_state, LICENSE_CONTACT)
    dp.message.middleware(gate)
    dp.callback_query.middleware(gate)

    # Админские роутеры регистрируются ПЕРЕД клиентским,
    # чтобы catch-all fallback_message не перехватил их сообщения
    dp.include_router(admin.router)
    dp.include_router(admin_appointments.router)
    dp.include_router(admin_clients.router)
    dp.include_router(admin_services.router)
    dp.include_router(admin_stats.router)
    dp.include_router(admin_status.router)
    dp.include_router(admin_settings.router)
    dp.include_router(admin_blocks.router)
    dp.include_router(admin_manage.router)
    dp.include_router(admin_masters.router)
    dp.include_router(admin_master_schedule.router)
    dp.include_router(admin_export.router)
    dp.include_router(admin_traffic.router)

    # Глобальный ловец unhandled exceptions из хендлеров.
    # Никогда ничего не должен поднимать — иначе aiogram паникует в polling loop.
    # Bot приходит через kwargs от диспетчера: ErrorEvent.bot в 3.7 = None.
    @dp.errors()
    async def on_handler_error(event: ErrorEvent, bot: Bot) -> bool:
        user_id: int | None = None
        context = "unknown"
        try:
            update = event.update
            if update.message is not None:
                if update.message.from_user is not None:
                    user_id = update.message.from_user.id
                text = update.message.text or update.message.caption or "(no text)"
                context = f"message: {text[:50]}"
            elif update.callback_query is not None:
                user_id = update.callback_query.from_user.id
                context = f"callback: {update.callback_query.data}"
        except Exception:
            # Парсинг обновления — best-effort. Не поломает алерт.
            pass
        logger.error("Unhandled exception in handler: %s", event.exception, exc_info=event.exception)
        await report_error(bot, event.exception, context=context, user_id=user_id)
        return True
    # master.router — ПОСЛЕ всех admin-роутеров, но ДО reviews/client_reminders/client_history/client:
    # IsMasterFilter поймает только активных мастеров с user_id, остальные провалятся дальше.
    dp.include_router(master.router)
    dp.include_router(reviews.router)  # до client.router — чтобы rev_* callbacks не попали в fallback
    # client_reminders и client_history — ДО client.router, т.к. client содержит
    # catch-all fallback_message. Порядок внутри этой тройки неважен (у них нет пересечений),
    # кроме того, что конкретные F-фильтры должны предшествовать catch-all message().
    dp.include_router(client_reminders.router)
    dp.include_router(client_history.router)
    dp.include_router(client.router)

    await init_db()
    await refresh_admins_cache()
    await refresh_masters_cache()

    # Запоминаем reply keyboard для админ-чатов
    for admin_id in ADMIN_IDS:
        set_reply_kb(admin_id, admin_reply_keyboard())

    # Регистрируем команду /language в меню бота (синяя «/»-кнопка в чате).
    # Отдельные версии для ru/uz — клиент видит подпись на своём языке
    # Telegram-клиента. Не фатально если упадёт — команда всё равно работает
    # через F.text.regexp, просто не появится в выпадающем меню.
    try:
        await bot.set_my_commands(
            [BotCommand(command="language", description="Сменить язык / Tilni o'zgartirish")],
        )
        await bot.set_my_commands(
            [BotCommand(command="language", description="Tilni o'zgartirish")],
            language_code="uz",
        )
    except Exception:
        logger.warning("Не удалось зарегистрировать /language в меню бота", exc_info=True)

    scheduler = setup_scheduler(bot, license_state)
    scheduler.start()

    # Payment webhook-server (Phase 1 v.4). Стартует в том же event loop
    # параллельно polling, только если PAYMENT_PROVIDER задан. В finally
    # аккуратно останавливаем runner.
    payment_runner = None
    from config import PAYMENT_PROVIDER
    if PAYMENT_PROVIDER != "none":
        try:
            from utils.payments.server import start_webhook_server
            payment_runner = await start_webhook_server(bot)
        except Exception:
            logger.exception("Payment webhook server не стартанул — платежи недоступны")

    mark_started()
    if license_state.mode == LicenseMode.GRACE:
        await _warn_grace(bot, license_state)
    logger.info("Бот запущен")

    try:
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        logger.info("Polling cancelled, shutting down")
    finally:
        logger.info("Бот останавливается.")
        scheduler.shutdown()
        if payment_runner is not None:
            try:
                await payment_runner.cleanup()
            except Exception:
                logger.warning("payment_runner cleanup: игнор")
        await close_db()
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
