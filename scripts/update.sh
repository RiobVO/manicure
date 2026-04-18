#!/usr/bin/env bash
# Обновление деплоя: подтянуть код из git и пересобрать контейнеры.
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.."

git pull --ff-only
docker compose up -d --build

echo ""
echo "Обновлено. Последние логи:"
docker compose logs --tail 20 bot || true
