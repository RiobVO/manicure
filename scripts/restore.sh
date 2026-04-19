#!/usr/bin/env bash
# Восстановление БД из бэкапа. Один шаг: остановить, подменить, запустить.
#
# Usage:
#   ./scripts/restore.sh <path/to/manicure_backup_X.db>
#
# Работает с любым валидным SQLite-файлом: локальный бэкап (./backups/),
# скачанный из Telegram-канала, ручной дамп. Сохраняет текущий файл как
# manicure.db.broken перед перезаписью — не удаляет данные молча.
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.."
DEPLOY_DIR="$(pwd)"

[[ $# -eq 1 ]] \
    || { echo "Usage: $0 <path/to/manicure_backup_X.db>"; exit 2; }

BACKUP="$1"
[[ -f "$BACKUP" ]] \
    || { echo "Файл $BACKUP не найден"; exit 2; }

# Санити-чек: это вообще SQLite?
if ! head -c 16 "$BACKUP" | grep -q "SQLite format 3"; then
    echo "Ошибка: $BACKUP не похож на SQLite-файл."
    echo "Убедись что это manicure_backup_*.db, а не .tar.gz или Telegram-JSON."
    exit 2
fi

DB="data/manicure.db"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

echo ""
echo "Восстановление из: $BACKUP"
echo "В:                 $DEPLOY_DIR/$DB"
echo ""
read -rp "Текущая БД будет сохранена как manicure.db.broken-$TIMESTAMP. Продолжить? [y/N] " answer
[[ "${answer,,}" == "y" ]] || { echo "Отменено."; exit 0; }

echo "Останавливаю bot..."
docker compose stop bot

if [[ -f "$DB" ]]; then
    mv "$DB" "${DB}.broken-${TIMESTAMP}"
    echo "Старая БД сохранена: ${DB}.broken-${TIMESTAMP}"
fi

# WAL/SHM-хвосты принадлежат старой БД, с новой они несовместимы.
rm -f "${DB}-wal" "${DB}-shm"

cp "$BACKUP" "$DB"
# chown чтобы контейнерный UID=1000 мог писать (как в install.sh).
chown 1000:1000 "$DB" 2>/dev/null || true

echo "Запускаю bot..."
docker compose start bot

echo ""
echo "Последние логи:"
docker compose logs --tail 20 bot || true

cat <<DONE

=== Восстановлено ===

Проверь:
  • docker compose logs -f bot       # бот стартовал без ошибок
  • /status в Telegram               # размер БД, uptime
  • список записей в админке         # данные на месте

Если что-то не так, откатить:
  docker compose stop bot
  mv ${DB}.broken-${TIMESTAMP} $DB
  docker compose start bot
DONE
