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

from zoneinfo import ZoneInfo

TZ: Final[ZoneInfo] = ZoneInfo(TIMEZONE)

# Deeplink для оплаты (опционально). Если не задано — кнопка оплаты не показывается.
# Пример: https://my.click.uz/services/pay?service_id=XXX&amount={amount}&transaction_param={appt_id}
PAYMENT_URL: Final[str | None] = os.getenv("PAYMENT_URL") or None
PAYMENT_LABEL: Final[str] = os.getenv("PAYMENT_LABEL", "Оплатить")

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
