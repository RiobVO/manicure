# FUTURE

Отложенные улучшения. Не делать до явного триггера.

## Замороженные фичи

- **Онлайн-оплата через бота (Click/Payme).** Phase 1 v.4 полностью
  реализована (utils/payments/{click,payme,server,base}.py, db/payments.py,
  UI-флоу в _bg_send_pay_link и cb_my_appt_detail, webhook-server на
  PAYMENT_WEBHOOK_PORT, миграции v2→v7). Сейчас отключена через
  PAYMENT_PROVIDER=none в .env — Сабина принимает оплату налом на месте.

  Почему заморозили: первый салон не требует предоплату, а интеграция
  с Click/Payme требует merchant-аккаунт (документы, KYC, ~1-2 недели)
  и реальное тестирование с деньгами. Для MVP это лишняя поверхность
  для багов.

  Триггеры активации (любой из):
    • Салон столкнулся с >15% no-show и хочет предоплату как рычаг.
    • Клиент попросил безнал (перевод по QR, карта — через Click).
    • Появился второй салон с требованием онлайн-оплаты.

  Что нужно сделать при активации:
    1. Получить merchant-аккаунт Click или Payme (Сабина сама, через
       свой ИНН/ООО).
    2. Заполнить в .env: CLICK_SERVICE_ID, CLICK_MERCHANT_ID,
       CLICK_MERCHANT_USER_ID, CLICK_SECRET_KEY, PAYMENT_PUBLIC_URL
       (или соответствующие PAYME_*).
    3. PAYMENT_PROVIDER=click (или payme).
    4. Настроить Caddy/nginx на VPS: проксировать /payment/click или
       /payment/payme на 127.0.0.1:8443.
    5. Указать callback URL в кабинете Click/Payme:
       https://<tenant>.<domain>/payment/click.
    6. Тест: сделать запись, оплатить 1000 UZS, проверить что webhook
       пришёл, paid_at проставился, pay-сообщение удалилось.
    7. Убрать warning-suppression в _bg_send_pay_link и cb_my_appt_detail
       (условия `if provider is not None or PAYMENT_URL`) — они
       замаскируют реальные проблемы с платежами в проде.

## Тех-долг после мастера-кабинета

- **HTML-экранирование клиентских данных** — имена/телефоны/услуги вставляются в
  `parse_mode="HTML"` без `html.escape()` в master.py, admin.py, admin_appointments.py.
  Триггер для фикса: клиент с `<` или `&` в имени сломает сообщение, или парсер
  начнёт интерпретировать имя как тег. Одним PR для всего проекта.
- **Логирование `pass` в except** — `handlers/master.py::_nav` делает `except Exception: pass`
  симметрично `handlers/admin.py::_nav`. CLAUDE.md требует логирование на error.
  При рефакторинге `_nav` привести оба файла к `logger.debug`.
- **Лишний `service_duration` в `get_master_appointments_upcoming`** — поле читается
  из SELECT, но в UI-слое (msg_upcoming) не используется. Можно убрать.

## UX и мелочи

- **Неизвестная команда у админа → клиентское меню.** Сейчас если админ шлёт
  `/foobar`, сообщение проваливается в `client.py::fallback_message` и показывает
  каталог услуг. Нужен админ-specific fallback: "Неизвестная команда, вот меню /status /restart ...".
  Триггер: первый раз, когда салон-админ пожалуется что «бот ведёт себя странно».

- **Включить license enforcement.** Код лицензирования (signing, verify, grace,
  heartbeat, middleware) полностью готов. Раскомментировать 3 строки в `bot.py`
  рядом с `# TODO: при ~20 клиентах`. Триггеры для включения:
  (а) дошли до 20 платящих салонов, (б) поймали первый случай попытки форка /
  переустановки без ключа, (в) наняли помощников по установке (своих больше не
  доверяешь в одностороннем порядке).

## Supply chain

- **Hash-pin в requirements.txt (`--require-hashes`).** Сейчас версии
  прибиты (aiogram, aiosqlite, apscheduler, python-dotenv, openpyxl,
  redis, cryptography, qrcode), но атака на PyPI через подмену
  уже опубликованного wheel'а (typosquat или компрометация
  maintainer'а) не ловится. Триггер: ≥10 платящих тенантов — тогда
  один компромет в апстриме задевает всех. Решение:
  `pip-compile --generate-hashes` + `pip install --require-hashes`
  в Dockerfile. До этого pin по версиям достаточно.

## Масштабируемое (из senior-upgrade-prompt.md §3)

- **Alembic** — при ~5 платящих тенантах.
- **Postgres / connection pooling** — когда один тенант стабильно >20 мастеров или
  booking latency >500ms.
- **Money value object** — когда первый клиент попросит скидки/gift cards/процентные промо.
- **Автоматический биллинг** — при ~10 платящих тенантах.
- **Property-тесты (hypothesis), mutation-тесты (mutmut), load-тесты (locust)** —
  когда booking-баг приведёт к жалобе в проде.
- **Multi-tenant shared DB** — вероятно никогда. Per-tenant VPS = фича.
- **i18n** — при первом не-русскоязычном клиенте.
- **Sentry вместо TG error channel** — при 20+ тенантах, когда группировка важнее
  пуша на телефон.

## Безопасность бэкапов

- **Шифровать бэкапы перед отправкой в Telegram-канал.** Сейчас `.db` уходит
  в приватный канал автора как есть — внутри телефоны и имена всех клиентов
  салона. TG шифрует транспорт, не storage. Триггеры: (а) 5+ салонов в портфеле,
  (б) первый клиент из ЕС/с PDN-требованиями, (в) случайный форвард бэкапа в
  не тот чат. Решение: `age` (один статический бинарь, $0), публичный ключ в
  `.env` как `BACKUP_PUBKEY`, приватный офлайн у автора. Шифрование в
  `scheduler.run_backup` через `subprocess.run(["age", "-r", pubkey, ...])`.
  Восстановление — `age -d -i ~/backup.key backup.db.age > backup.db`.
  Пока один-два салона + 2FA на TG-аккаунте автора — не трогать.

## Из Phase 7 (по запросу)

- **Fleet dashboard** — FastAPI + htmx страница с heartbeat'ами всех тенантов.
  Триггер: когда у автора ~30 тенантов и он тонет в ручном мониторинге.

## Платежи (v.4 Phase 1 MVP → полноценный)

> Сам провайдер заморожен — см. «Замороженные фичи» выше. Пункты ниже —
> продолжение работ **когда** оплату включат обратно.

- **Авто-рефанд при отмене оплаченной записи.** Сейчас только alert админу
  (`admin_dismiss_kb("✅ Возврат сделан")`). Click `payment/revert` и
  Payme `CancelTransaction` — реализовать в `utils/payments/*.py`. Триггер:
  (а) 3+ отмены оплаченных в месяц, (б) первый админ пожалуется что устал
  вручную рефандить. Требует реального merchant-аккаунта для тестов.

- **Цена услуги ≠ pay_url сумма.** Если админ поднимет прайс между
  `confirm_yes` и реальной оплатой — клиент заплатит старую сумму.
  Edge case. Фикс: либо лочить `services.price` пока есть активный invoice
  на услугу, либо при UPDATE price инвалидировать все нерасчитанные
  invoice'ы (создавать новый с актуальной ценой). Триггер: первая жалоба
  «клиент заплатил не столько».

- **Реальный Click end-to-end тест.** Сейчас только моком. Фикс невозможен
  в коде — нужен реальный merchant-аккаунт и тестовый платёж. Триггер:
  получил доступ к Click production API.

## Из аудита 2026-04-22

- **Rate-limit webhook за reverse-proxy.** `request.remote` после Caddy/nginx
  всегда будет 127.0.0.1 — все провайдеры будут шарить один bucket, легитимные
  Click/Payme могут получить 429. Плюс утечка памяти: `_rate_log` не удаляет
  пустые ключи IP. Фикс: читать `X-Forwarded-For`, очищать пустые deque.
  Триггер: ставим Caddy/nginx перед ботом или используем webhook-tunnel
  с shared-IP. Сейчас docker биндится напрямую — `request.remote` = реальный IP
  провайдера, не ломается.

- **`asyncio.timeout(1.5)` вокруг `BEGIN IMMEDIATE`.** Зависший `await` под
  write-lock сейчас замораживает весь бот: все записи встают в очередь одного
  lock'а. Timeout даст бизнес-ошибку вместо вечной очереди. Триггер: первый
  инцидент с «бот завис на минуту» в проде.

- **Refactor `handlers/client.py`** (1279 строк). `_do_confirm` ≈260 строк +
  4 вложенных `_bg_*` closure — нечитаемо. Вынести: booking-finalize
  в `services/booking.py`, рендер summary в `utils/ui.py::render_booking_summary`,
  закрытия в `utils/notifications.py::notify_new_booking`. Триггер: следующий
  баг в booking-flow, где понадобится менять `_do_confirm`.

- **i18n labels helper.** Сейчас `if lang == "uz"` размазан в 5 местах
  (`_render_summary`, `_do_confirm`, `client_history`, `scheduler._send_*h_reminder`).
  Добавить `utils/i18n.py::labels(lang) -> dict` с ключами `service_label`,
  `master_label` и т.д. Триггер: первое добавление языка помимо ru/uz.

- **Overlap-SQL builder.** 4 почти идентичных SQL-фрагмента в
  `db/appointments.py` (`create_appointment` и `reschedule_appointment` ×
  master/no-master). Вынести `_count_overlaps(date, time, duration, master_id,
  exclude_id) -> int`. Триггер: следующий багфикс overlap-формулы —
  чтобы не править в 4 местах и не расходиться.

- **`:` разделитель вместо `_` в callback-data.** `parse_callback` хрупок
  на префиксах с `_` (коды траффика `story_apr20` уже содержат). Триггер:
  первый случай, когда whitelist отказал корректному коду.

- **Системный HTML-escape.** Ручной `h()` в каждом f-string — забытый `h`
  = BadRequest, которое глотается в `except`. Переход на
  `Bot(default=DefaultBotProperties(parse_mode="HTML"))` + единая
  `safe_format()` — большой рефакторинг. Триггер: перед добавлением 3-го
  языка или после первой молчаливой потери сообщения в проде.

- **TTL у `_confirm_in_progress`.** Если `_do_confirm` упадёт до `finally`,
  user_id залипнет в set — новый /start не поможет. Сейчас try/finally
  защищает, но defence-in-depth: хранить `time.monotonic()` и чистить
  старше 30 сек. Триггер: первая жалоба «бот не реагирует на записаться»
  без видимых ошибок в логах.

- **Модульный state → Redis.** `_client_services_msg`, `_bg_tasks`,
  `_db_admins_cache`, `_panel_msg_ids`, `_rate_log`, `_last_error` — всё
  в памяти процесса. Триггер: миграция на 2+ worker (вероятно — никогда
  в рамках one-tenant-one-VPS).
