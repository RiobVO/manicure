# Восстановление БД

Когда нужно: диск упал, дроплет умер, `manicure.db` повреждён, клиент звонит в 22:00.

## Источник бэкапа

Выбираем самый свежий:

1. **Локальный** — `./backups/manicure_backup_YYYY-MM-DD_HH-MM.db` (последние 7, ротация).
2. **Telegram-канал** — файл с подписью `[tenant_slug] backup ... • N MB`. Скачиваем, переименовываем в `manicure.db`.

## Шаги (docker-compose)

```bash
docker compose stop bot              # бот не должен держать БД открытой
cp manicure.db manicure.db.broken    # сохраняем битую на всякий случай
rm -f manicure.db-wal manicure.db-shm  # удаляем WAL-хвосты — они от старой БД
cp backups/manicure_backup_<timestamp>.db manicure.db
docker compose start bot
docker compose logs -f bot | head -30  # убедиться что стартовал без ошибок
```

## Проверка

В боте от админ-аккаунта: открыть список записей. Если даты и клиенты на месте — восстановились.

## Если бэкапа нет

Такого сценария у нас нет: локальный пишется каждые 6ч, Telegram-копия — тоже. Если оба пусты — сначала проверь `./backups/` и историю канала. Последний рубеж — `manicure.db.broken` + утилита `sqlite3 .recover`.
