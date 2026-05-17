#!/usr/bin/env bash
# Сброс демо-бота к чистому состоянию между показами в салонах.
#
# Когда использовать:
#   • После показа одному салону, перед следующим — чтобы менеджер не
#     видел записи предыдущего демо.
#   • Если демо-БД засрана тестовыми услугами/мастерами/записями.
#
# Что делает:
#   1. Останавливает контейнеры (docker compose down, без -v — redis-volume
#      не трогаем, там только FSM-state, чистится сам за 24ч по TTL).
#   2. Удаляет data/manicure.db + WAL/SHM + .heartbeat.
#   3. Поднимает заново — init_db создаст свежую схему с seed-услугами.
#   4. Ждёт 10 сек, печатает последние логи.
#
# Что НЕ трогает:
#   • backups/ — там страховка, на всякий случай.
#   • .env — токен/slug/admin_id остаются теми же.
#   • redis — FSM-state, эфемерный, чистится сам.
#
# ВНИМАНИЕ: не запускай на боевом боте салона! Скрипт безусловно стирает БД.
# Проверка tenant_slug ниже — наивная страховка, поменяй на свой демо-slug.
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.."

# Страховка: если .env содержит не-демо tenant_slug — требуем явное подтверждение.
# Меняй DEMO_SLUGS под свои имена демо-инстансов.
DEMO_SLUGS=("demo-nails" "demo" "test" "sabina-nails")
CURRENT_SLUG=$(grep "^TENANT_SLUG=" .env 2>/dev/null | cut -d= -f2 | tr -d '"' || echo "")

is_demo=false
for s in "${DEMO_SLUGS[@]}"; do
    [[ "$CURRENT_SLUG" == "$s" ]] && is_demo=true && break
done

if [[ "$is_demo" != true ]]; then
    echo "⚠ TENANT_SLUG='$CURRENT_SLUG' не в списке демо-slug'ов."
    echo "   Если это действительно демо — добавь slug в DEMO_SLUGS в скрипте."
    echo "   Если это боевой салон — НЕ ЗАПУСКАЙ этот скрипт, он удалит БД."
    read -rp "   Продолжить и стереть БД? Введи 'yes' для подтверждения: " confirm
    [[ "$confirm" == "yes" ]] || { echo "Отменено."; exit 0; }
fi

echo "→ Останавливаю контейнеры..."
docker compose down

echo "→ Удаляю БД и heartbeat..."
rm -f data/manicure.db data/manicure.db-wal data/manicure.db-shm data/.heartbeat
rm -f data/.license_alert  # чтобы алерт о лицензии сбросился для демо

echo "→ Поднимаю с чистой БД..."
docker compose up -d

echo "→ Ждём 10 сек пока бот стартует..."
sleep 10

echo ""
echo "=== Последние логи ==="
docker compose logs bot --tail 10 || true

echo ""
echo "✓ Демо сброшено. TENANT_SLUG=$CURRENT_SLUG"
echo "  Напиши /start своему демо-боту — должен поздороваться как с новым клиентом."
