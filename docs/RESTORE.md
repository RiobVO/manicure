# Восстановление БД

Когда нужно: диск упал, дроплет умер, `manicure.db` повреждён, клиент звонит в 22:00.

## Источник бэкапа

Выбираем самый свежий:

1. **Локальный** — `./backups/manicure_backup_YYYY-MM-DD_HH-MM.db` (последние 7, ротация).
2. **Telegram-канал** — файл с подписью `[tenant_slug] backup ... • N MB`. Скачиваем в `./backups/`.

## Шаги (docker-compose)

> **ВАЖНО:** рабочая БД лежит в `./data/manicure.db` (bind-mount на `/app/data/manicure.db` внутри контейнера). Команды ниже работают с `data/`, НЕ с корнем репо — иначе бот после старта увидит пустую БД и все записи дня потеряются.

```bash
docker compose stop bot                                    # бот не должен держать БД открытой
cp data/manicure.db data/manicure.db.broken                # сохраняем битую на всякий случай
rm -f data/manicure.db-wal data/manicure.db-shm            # WAL-хвосты от старой БД не тащим
cp backups/manicure_backup_<timestamp>.db data/manicure.db # кладём бэкап ровно в рабочий путь
chown 1000:1000 data/manicure.db                           # контейнер запускается под UID=1000
docker compose start bot
docker compose logs -f bot | head -50                      # убедиться что стартовал без ошибок
```

## Проверка

В боте от админ-аккаунта: открыть список записей. Если даты и клиенты на месте — восстановились.

## Если бэкапа нет

Такого сценария у нас нет: локальный пишется каждые 6ч, Telegram-копия — тоже. Если оба пусты — сначала проверь `./backups/` и историю канала. Последний рубеж — `data/manicure.db.broken` + утилита `sqlite3 .recover`.
