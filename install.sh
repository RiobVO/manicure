#!/usr/bin/env bash
# Установщик инстанса бота для одного салона.
# Usage: ./install.sh <tenant_slug> <bot_token> <admin_id>
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

usage() {
    cat <<USAGE
Usage: ./install.sh <tenant_slug> <bot_token> <admin_id>

  tenant_slug   Идентификатор салона, [a-z0-9-], например 'nails-chilanzar'.
  bot_token     Токен от @BotFather.
  admin_id      Telegram user_id владельца салона (целое число).

Пример: ./install.sh nails-chilanzar 1234567890:ABC... 7082498953
USAGE
    exit 2
}

[[ $# -eq 3 ]] || usage

TENANT_SLUG="$1"
BOT_TOKEN="$2"
ADMIN_ID="$3"

[[ "$TENANT_SLUG" =~ ^[a-z0-9-]+$ ]] \
    || { echo "Ошибка: tenant_slug должен матчить [a-z0-9-]+"; exit 2; }
[[ "$ADMIN_ID" =~ ^[0-9]+$ ]] \
    || { echo "Ошибка: admin_id должен быть целым числом"; exit 2; }

if ! command -v docker >/dev/null 2>&1; then
    echo "Не найден docker. Установи на Ubuntu одной командой:"
    echo "  curl -fsSL https://get.docker.com | sh"
    exit 3
fi
if ! docker compose version >/dev/null 2>&1; then
    echo "Не найден docker compose v2. Установи docker-compose-plugin:"
    echo "  apt-get install -y docker-compose-plugin"
    exit 3
fi

if [[ -f .env ]]; then
    cp .env ".env.bak.$(date +%s)"
    echo "Найден существующий .env → сохранён в .env.bak.*"
fi

BACKUP_CHAT_ID=""
read -rp "Настроить облачный бэкап в Telegram? [y/N] " answer
if [[ "${answer,,}" == "y" ]]; then
    read -rp "BACKUP_CHAT_ID (напр. -1001234567890): " BACKUP_CHAT_ID
    [[ "$BACKUP_CHAT_ID" =~ ^-?[0-9]+$ ]] \
        || { echo "Ошибка: BACKUP_CHAT_ID должен быть числом"; exit 2; }
fi

ERROR_CHAT_ID=""
read -rp "Настроить алерты об ошибках в Telegram? [y/N] " answer
if [[ "${answer,,}" == "y" ]]; then
    read -rp "ERROR_CHAT_ID (можно тот же канал что для бэкапов): " ERROR_CHAT_ID
    [[ "$ERROR_CHAT_ID" =~ ^-?[0-9]+$ ]] \
        || { echo "Ошибка: ERROR_CHAT_ID должен быть числом"; exit 2; }
fi

LICENSE_KEY=""
read -rp "Лицензионный ключ (от tools/issue_license.py; Enter — пропустить, бот будет в restricted): " LICENSE_KEY

HEARTBEAT_URL=""
read -rp "URL heartbeat-эндпоинта (Enter — не слать): " HEARTBEAT_URL

LICENSE_CONTACT=""
read -rp "Контакт поставщика для сообщения об истечении лицензии (@handle или email, Enter — дефолт): " LICENSE_CONTACT

# Генерация .env из шаблона. sed с разделителем | чтобы не спотыкаться о / в токенах.
# LICENSE_KEY экранируем отдельно: он содержит точку-разделитель payload/sig и base64.
sed \
    -e "s|__BOT_TOKEN__|${BOT_TOKEN}|" \
    -e "s|__ADMIN_IDS__|${ADMIN_ID}|" \
    -e "s|__TENANT_SLUG__|${TENANT_SLUG}|" \
    -e "s|__BACKUP_CHAT_ID__|${BACKUP_CHAT_ID}|" \
    -e "s|__ERROR_CHAT_ID__|${ERROR_CHAT_ID}|" \
    -e "s|__LICENSE_KEY__|${LICENSE_KEY}|" \
    -e "s|__HEARTBEAT_URL__|${HEARTBEAT_URL}|" \
    -e "s|__LICENSE_CONTACT__|${LICENSE_CONTACT}|" \
    .env.template > .env
chmod 600 .env

mkdir -p data backups

echo ""
echo "Сборка образа и запуск контейнеров..."
docker compose up -d --build

echo ""
echo "Ожидаем старта бота (до 30 сек)..."
for i in $(seq 1 30); do
    if docker compose logs bot 2>&1 | grep -q "Бот запущен"; then
        echo "Бот стартовал за ${i} сек."
        break
    fi
    sleep 1
done

echo ""
echo "=== Последние логи бота ==="
docker compose logs --tail 20 bot || true

cat <<NEXT

=== Установка завершена ===

Салон:        ${TENANT_SLUG}
Админ:        ${ADMIN_ID}
Бэкап в TG:   ${BACKUP_CHAT_ID:-отключён}

Что дальше:
  • Проверь бот в Telegram: /start от admin_id=${ADMIN_ID}
  • Живые логи:     docker compose logs -f bot
  • Обновление:     ./scripts/update.sh
  • Удаление:       ./scripts/uninstall.sh
  • Восстановление БД: docs/RESTORE.md
NEXT
