#!/usr/bin/env bash
# Удаление деплоя с предварительным архивом данных.
# НИКОГДА не удаляет данные молча: всё идёт в /root/manicure-<tenant>-<date>.tar.gz.
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.."
DEPLOY_DIR="$(pwd)"

read -rp "Удалить деплой из '$DEPLOY_DIR'? Данные будут заархивированы в /root/. Введи 'yes': " confirm
[[ "$confirm" == "yes" ]] || { echo "Отменено."; exit 0; }

TENANT=$(grep ^TENANT_SLUG= .env 2>/dev/null | cut -d= -f2 | tr -d '"' || echo "unknown")
TIMESTAMP=$(date +%Y%m%d-%H%M)
ARCHIVE="/root/manicure-${TENANT}-${TIMESTAMP}.tar.gz"

echo "Архивируем data/ backups/ .env → $ARCHIVE ..."
tar -czf "$ARCHIVE" data backups .env 2>/dev/null || true
ls -lh "$ARCHIVE"

echo ""
echo "Останавливаем контейнеры и удаляем volumes Redis..."
docker compose down -v || true

echo ""
echo "Удаляем каталог деплоя: $DEPLOY_DIR"
cd /
rm -rf "$DEPLOY_DIR"

echo ""
echo "Готово. Данные салона сохранены: $ARCHIVE"
