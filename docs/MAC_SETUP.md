# Демо-бот на Mac (M1+)

Поднять локальный демо-бот для показов в салонах. ~20 минут с нуля.

## 1. Docker Desktop

Скачать: <https://desktop.docker.com/mac/main/arm64/Docker.dmg> (Intel-мак: `amd64` вместо `arm64`).

Перетащить в Applications → запустить → пароль мака → skip tutorial → skip Docker Hub login.

Ждать пока 🐳 в меню-баре перестанет мигать.

## 2. Git

```bash
git --version
```

Всплывёт «Install developer tools?» → Install → ~5 минут.

## 3. Клон + демо-бот

В Telegram: [@BotFather](https://t.me/BotFather) → `/newbot` → придумать username на `*_bot` → скопировать токен.

[@userinfobot](https://t.me/userinfobot) → любое сообщение → скопировать свой user_id.

В Terminal:

```bash
cd ~ && git clone https://github.com/RiobVO/manicure.git && cd manicure
cp .env.template .env
open -e .env
```

В `.env` заменить плейсхолдеры:

```
BOT_TOKEN=<токен из BotFather>
ADMIN_IDS=<твой user_id>
TENANT_SLUG=demo-nails
REDIS_URL=redis://redis:6379/0
TIMEZONE=Asia/Tashkent
LICENSE_KEY=
```

Остальные поля — пустые.

## 4. Запуск

```bash
mkdir -p data backups
docker compose up -d --build
```

Первая сборка ~90 сек, дальше `up -d` = 5 сек.

Проверка: пиши боту `/start` — должна открыться админ-панель.

## 5. Ежедневно

```bash
docker compose up -d        # утро
docker compose down         # вечер
./scripts/reset_demo.sh     # между салонами — чистит БД
```

## Сломалось

- Бот молчит → `docker compose logs bot --tail 30`, обычно неверный токен в `.env`.
- После ребута мака не стартует → открой Docker Desktop из Launchpad.
- Нет места → `docker system prune -a`.

Всё остальное (продление лицензий, продажа клиенту, восстановление БД) — в `SALE_PLAYBOOK.md`, `LICENSING.md`, `RESTORE.md`.
