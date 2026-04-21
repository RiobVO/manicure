"""
Конфигурация окружения. Загружается из .env через python-dotenv.

Все переменные, относящиеся к поведению (длина окна бронирования, минимальный
запас времени и т.д.) — в constants.py. Здесь только то, что берётся из
окружения или инфраструктуры.
"""
import os
from typing import Final

from dotenv import load_dotenv

load_dotenv()


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise EnvironmentError(f"Required environment variable '{name}' is missing or empty.")
    return value


BOT_TOKEN: Final[str] = _require_env("BOT_TOKEN")

try:
    ADMIN_IDS: Final[frozenset[int]] = frozenset(
        int(x.strip()) for x in _require_env("ADMIN_IDS").split(",") if x.strip()
    )
except ValueError as exc:
    raise EnvironmentError(
        "ADMIN_IDS must be comma-separated integers, e.g. 123456,789012."
    ) from exc

# Путь к SQLite-файлу. Можно переопределить через .env, по умолчанию — рядом с ботом.
DB_PATH: Final[str] = os.getenv("DB_PATH", "manicure.db")

TIMEZONE: Final[str] = os.getenv("TIMEZONE", "Asia/Tashkent")

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    TZ: Final[ZoneInfo] = ZoneInfo(TIMEZONE)
except ZoneInfoNotFoundError as exc:
    # Fail-fast с человеческим сообщением, чтобы оператор сразу понял куда смотреть.
    raise EnvironmentError(
        f"TIMEZONE='{TIMEZONE}' не найден. Укажи IANA-имя, например Asia/Tashkent, Europe/Moscow."
    ) from exc

# ─── Платежи (v.4 Phase 1) ──────────────────────────────────────────
# Legacy: чистый deeplink. Работает рядом с PAYMENT_PROVIDER=none.
# Используется только если PAYMENT_PROVIDER=none — для салонов, кто не хочет
# полную интеграцию (мерчант не оформлен) и готов проставлять оплату руками.
PAYMENT_URL: Final[str | None] = os.getenv("PAYMENT_URL") or None
PAYMENT_LABEL: Final[str] = os.getenv("PAYMENT_LABEL", "Оплатить")

# Провайдер: click | payme | none. "none" → показываем legacy PAYMENT_URL если задан.
PAYMENT_PROVIDER: Final[str] = os.getenv("PAYMENT_PROVIDER", "none").strip().lower()
if PAYMENT_PROVIDER not in {"click", "payme", "none"}:
    raise EnvironmentError(
        f"PAYMENT_PROVIDER='{PAYMENT_PROVIDER}' недопустим. Допустимые: click | payme | none."
    )

# Click — https://docs.click.uz/click-api-request/
CLICK_SERVICE_ID: Final[str] = os.getenv("CLICK_SERVICE_ID", "").strip()
CLICK_MERCHANT_ID: Final[str] = os.getenv("CLICK_MERCHANT_ID", "").strip()
CLICK_MERCHANT_USER_ID: Final[str] = os.getenv("CLICK_MERCHANT_USER_ID", "").strip()
CLICK_SECRET_KEY: Final[str] = os.getenv("CLICK_SECRET_KEY", "").strip()
# Для локального теста: направляем invoice-create на mock (tools/mock_click_server.py).
# Дефолт — прод. Пример для dev: http://localhost:8444/mock-click/v2/merchant
CLICK_API_BASE: Final[str] = os.getenv(
    "CLICK_API_BASE", "https://api.click.uz/v2/merchant"
).rstrip("/")
# База для pay_url, которую клиент откроет в браузере. Пусто → прод my.click.uz.
CLICK_PAY_URL_BASE: Final[str] = os.getenv(
    "CLICK_PAY_URL_BASE", "https://my.click.uz/services/pay"
).rstrip("?")

# Payme — https://developer.help.paycom.uz/merchant-api/
PAYME_MERCHANT_ID: Final[str] = os.getenv("PAYME_MERCHANT_ID", "").strip()
PAYME_SECRET_KEY: Final[str] = os.getenv("PAYME_SECRET_KEY", "").strip()

# Публичный HTTPS-URL, куда Caddy/nginx проксирует webhook'и. Пусто → сервер не стартует.
PAYMENT_PUBLIC_URL: Final[str] = os.getenv("PAYMENT_PUBLIC_URL", "").rstrip("/")
PAYMENT_WEBHOOK_PORT: Final[int] = int(os.getenv("PAYMENT_WEBHOOK_PORT", "8443"))

# Fail-fast: если провайдер включён — все его креды обязаны быть заданы.
if PAYMENT_PROVIDER == "click":
    _missing = [
        k for k, v in {
            "CLICK_SERVICE_ID": CLICK_SERVICE_ID,
            "CLICK_MERCHANT_ID": CLICK_MERCHANT_ID,
            "CLICK_MERCHANT_USER_ID": CLICK_MERCHANT_USER_ID,
            "CLICK_SECRET_KEY": CLICK_SECRET_KEY,
            "PAYMENT_PUBLIC_URL": PAYMENT_PUBLIC_URL,
        }.items() if not v
    ]
    if _missing:
        raise EnvironmentError(
            f"PAYMENT_PROVIDER=click, но не заданы: {', '.join(_missing)}"
        )
elif PAYMENT_PROVIDER == "payme":
    _missing = [
        k for k, v in {
            "PAYME_MERCHANT_ID": PAYME_MERCHANT_ID,
            "PAYME_SECRET_KEY": PAYME_SECRET_KEY,
            "PAYMENT_PUBLIC_URL": PAYMENT_PUBLIC_URL,
        }.items() if not v
    ]
    if _missing:
        raise EnvironmentError(
            f"PAYMENT_PROVIDER=payme, но не заданы: {', '.join(_missing)}"
        )

# Redis для персистентного FSM-storage. Пусто → MemoryStorage (FSM теряется при рестарте).
# Формат: redis://[:password@]host:port/db, например redis://redis:6379/0.
REDIS_URL: Final[str] = os.getenv("REDIS_URL", "")

# Идентификатор салона-арендатора (для caption в бэкапах и тегов логов).
# Заполняется install.sh при деплое. Дефолт — для локальной разработки.
TENANT_SLUG: Final[str] = os.getenv("TENANT_SLUG", "unknown")

# Telegram chat_id для облачной копии БД. Пусто → только локальные бэкапы.
# Рекомендуется приватный канал, где владелец = автор бота.
try:
    _backup_chat = os.getenv("BACKUP_CHAT_ID", "").strip()
    BACKUP_CHAT_ID: Final[int | None] = int(_backup_chat) if _backup_chat else None
except ValueError as exc:
    raise EnvironmentError(
        "BACKUP_CHAT_ID must be an integer (Telegram chat_id), e.g. -1001234567890."
    ) from exc

# Telegram chat_id приватного канала для алертов об ошибках. Пусто → алертов нет,
# ошибки только в stderr контейнера. Рекомендуется канал, куда автор получает пуши.
try:
    _error_chat = os.getenv("ERROR_CHAT_ID", "").strip()
    ERROR_CHAT_ID: Final[int | None] = int(_error_chat) if _error_chat else None
except ValueError as exc:
    raise EnvironmentError(
        "ERROR_CHAT_ID must be an integer (Telegram chat_id)."
    ) from exc

# Лицензионный ключ (вывод tools/issue_license.py). Пусто + реальный публичный ключ
# в utils/license.py → restricted mode.
LICENSE_KEY: Final[str] = os.getenv("LICENSE_KEY", "").strip()

# URL для heartbeat-POST (автор-контролируемый endpoint). Пусто → heartbeat не шлём.
HEARTBEAT_URL: Final[str] = os.getenv("HEARTBEAT_URL", "").strip()

# Контакт для сообщения «лицензия истекла, обратитесь к X». Например: @sabina_nails_author.
LICENSE_CONTACT: Final[str] = os.getenv("LICENSE_CONTACT", "поставщика бота")
