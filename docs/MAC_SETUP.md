# Установка демо-бота на Mac (M1 / M2 / M3)

> **Для автора.** Цель — поднять локальный демо-бот на маке, чтобы
> носить его в салоны и показывать клиентам в живую. Документ
> пошаговый, с нуля, как будто мак только распакован.
>
> Итог после прохождения — `./scripts/reset_demo.sh` между показами,
> docker compose up/down для начала/конца дня.
>
> Время на установку: ~30 минут (из них 15 минут — ожидание скачиваний).

---

## Что понадобится

- Мак с Apple Silicon (M1 / M2 / M3 / M4). Intel-маки тоже подойдут,
  но скачивать нужно **другой** установщик Docker — ссылка ниже.
- Интернет для первичной установки.
- Пароль администратора мака (пару раз потребуется `sudo`).
- Telegram-аккаунт — для создания демо-бота.

---

## Шаг 1 — Docker Desktop

Ядро системы. Без него ничего не запустится.

### 1.1. Скачать

Прямые ссылки (без захода на сайт):

- **Apple Silicon (M1/M2/M3/M4):** <https://desktop.docker.com/mac/main/arm64/Docker.dmg>
- **Intel Mac (старый):** <https://desktop.docker.com/mac/main/amd64/Docker.dmg>

Файл ~600 MB, скачается минут за 2-5.

### 1.2. Установить

1. Открой скачанный `Docker.dmg` (двойной клик в папке Downloads).
2. Перетяни иконку **Docker** на иконку **Applications** в открывшемся окне.
3. Открой Launchpad → найди **Docker** → запусти.
4. Всплывёт окно «Docker Desktop needs privileged access» → **OK** →
   введи пароль мака.
5. Прими пользовательское соглашение (галочка внизу + Accept).
6. Tutorial — **Skip** (Cmd+W или «Skip» в правом верхнем углу).
7. Login to Docker Hub — **Continue without signing in** (внизу).

### 1.3. Дождаться старта

В меню-баре (верхняя полоса мака) появится значок 🐳. Когда **перестанет
анимироваться / мигать** — Docker готов.

### 1.4. Проверить

Открой **Terminal** (Cmd+Space → «terminal» → Enter):

```bash
docker --version
docker compose version
```

Обе команды должны вывести версии без ошибок. Если ошибка «command not
found» — значит Docker Desktop не запущен, открой его из Launchpad.

---

## Шаг 2 — Git и Xcode Command Line Tools

Нужно для клонирования репозитория.

### 2.1. Проверить

```bash
git --version
```

- Если вывелось `git version 2.x.x` — у тебя всё есть, пропускай шаг 2.
- Если всплыло окно «The "git" command requires the command line
  developer tools. Would you like to install them?» — жми **Install**.
- Пропущено? Запусти принудительно:

  ```bash
  xcode-select --install
  ```

### 2.2. Дождаться установки

Загружается ~500 MB, занимает 5-10 минут. Окно само закроется
«Software was installed». Проверь ещё раз `git --version` — теперь
должен отвечать.

---

## Шаг 3 — Клонировать проект

```bash
mkdir -p ~/PycharmProjects
cd ~/PycharmProjects
git clone https://github.com/RiobVO/manicure.git
cd manicure
```

После этого ты в папке `/Users/ТВОЁ_ИМЯ/PycharmProjects/manicure`.
Проверь:

```bash
ls
```

Должен увидеть `bot.py`, `docker-compose.yml`, `handlers/`, `docs/` и т.д.

---

## Шаг 4 — Создать демо-бота в Telegram

Демо-бот — отдельный от всех боевых. Его ты будешь показывать всем
подряд. Токены боевых клиентов сюда не кладём.

### 4.1. В BotFather

1. Открой Telegram → найди [@BotFather](https://t.me/BotFather) → открой.
2. Напиши `/newbot`.
3. На «Alright, a new bot. How are we going to call it?» введи имя
   (человеческое): `Manicure Demo`.
4. На «good. Now let's choose a username» введи уникальный username,
   который оканчивается на `bot`: например `manicure_demo_bot` или
   `plssog_demo_bot`. Если занято — BotFather скажет, пробуй другое.
5. BotFather пришлёт сообщение с токеном вида
   `1234567890:ABCdefGhIJKLmnopQRSTuvwxyz-0123`. **Скопируй его**
   в заметки — будет нужно через минуту.

### 4.2. Узнать свой user_id

1. Открой [@userinfobot](https://t.me/userinfobot) → напиши что угодно.
2. Он пришлёт твой числовой ID, например `7082498953`. Тоже сохрани.

---

## Шаг 5 — Настроить `.env`

Это конфиг демо-бота.

### 5.1. Создать файл из шаблона

```bash
cp .env.template .env
```

### 5.2. Открыть в редакторе

```bash
open -e .env
```

Откроется TextEdit. Замени плейсхолдеры `__XXX__` на реальные значения:

```
BOT_TOKEN=1234567890:ABCdefGhIJKLmnopQRSTuvwxyz-0123
ADMIN_IDS=7082498953
TENANT_SLUG=demo-nails
REDIS_URL=redis://redis:6379/0
TIMEZONE=Asia/Tashkent
LICENSE_KEY=
BACKUP_CHAT_ID=
ERROR_CHAT_ID=
HEARTBEAT_URL=
LICENSE_CONTACT=@plssog
```

Что зачем:

| Поле | Что это |
|---|---|
| `BOT_TOKEN` | Из BotFather, шаг 4.1 |
| `ADMIN_IDS` | Твой user_id из @userinfobot, шаг 4.2 |
| `TENANT_SLUG` | `demo-nails` — скрипт `reset_demo.sh` знает этот slug |
| `REDIS_URL` | Оставить как есть — Docker сам разрулит |
| `TIMEZONE` | `Asia/Tashkent` для УЗ, `Europe/Moscow` для России и т.п. |
| `LICENSE_KEY` | **Пусто** — демо не нуждается в лицензии, режим DEV |
| `BACKUP_CHAT_ID` | Пусто — демо бэкапить не нужно |
| `ERROR_CHAT_ID` | Пусто (или твой приватный канал, если хочешь видеть краши) |
| `HEARTBEAT_URL` | Пусто |
| `LICENSE_CONTACT` | Твой @handle, на всякий случай |

Сохрани (Cmd+S), закрой TextEdit (Cmd+W).

---

## Шаг 6 — Подготовить папки и запустить

```bash
mkdir -p data backups
docker compose up -d --build
```

**Что происходит:**

- Docker собирает образ бота (~60-90 секунд на M1, **только первый раз**).
- Поднимает 3 контейнера: `bot`, `redis`, `autoheal`.
- Бот подключается к Telegram API и начинает слушать сообщения.

**Ожидаемый вывод в конце:**

```
 ✔ Container manicure-redis-demo-nails      Healthy
 ✔ Container manicure-bot-demo-nails        Started
 ✔ Container manicure-autoheal-demo-nails   Started
```

### 6.1. Проверить что бот живой

```bash
docker compose ps
```

Все три контейнера должны быть в статусе **Up** (для `redis` — Up healthy).

```bash
docker compose logs bot --tail 30
```

В хвосте логов должна быть строка:

```
Бот запущен
```

Если её нет и есть какая-то ошибка — копируй ошибку в чат, разберёмся.

### 6.2. Проверить бота в Telegram

1. Открой Telegram → найди своего бота по username
   (`@manicure_demo_bot` или что ты придумал).
2. Нажми **Start** (или напиши `/start`).
3. Должна открыться админ-панель с reply-клавиатурой
   (📋 Сегодня / 🗓 Календарь / 💅 Услуги / и т.д.).

**Работает** — поздравляю, демо готов.

---

## Шаг 7 — Ежедневная работа

### Утро: включить демо

```bash
cd ~/PycharmProjects/manicure
docker compose up -d
```

(Без `--build` — образ уже собран. Занимает 3-5 секунд.)

### Вечер: выключить

```bash
docker compose down
```

Контейнеры остановятся, данные останутся в `data/`.

**Важно:** Docker Desktop должен оставаться запущенным (в меню-баре
🐳). Не закрывай его через Cmd+Q — контейнеры остановятся.

### Между показами в разных салонах: сбросить БД

```bash
./scripts/reset_demo.sh
```

Удаляет БД (записи предыдущего менеджера), перезапускает бот — через
15 секунд демо чистое.

---

## Шаг 8 — Если что-то сломалось

### «Бот не отвечает на /start»

1. `docker compose ps` — все 3 контейнера Up?
2. `docker compose logs bot --tail 50` — ищи `ERROR` или `TelegramAPIError`.
3. Частая причина: неверный `BOT_TOKEN` в `.env`. Скопируй ещё раз
   из BotFather (`/mybots` → выбери бота → API Token), обнови `.env`,
   `docker compose restart bot`.

### «После ребута мака не запускается»

Docker Desktop не запустился сам. Открой из Launchpad → подожди пока
кит стабилизируется → `docker compose up -d`.

### «Закончилось место на диске»

```bash
docker system prune -a
```

Удалит неиспользуемые образы и слои. У меня на маке занимает ~3 GB
после пары дней использования.

### «Бот лагает, долго отвечает»

Открой Docker Desktop → Settings (шестерёнка сверху) → Resources →
увеличь RAM до 4 GB (если мак 16 GB+) или 2 GB (если 8 GB). Apply & Restart.

---

## Шаг 9 — Полный сброс (если нужно начать с нуля)

Ядерный вариант — снести всё, начать заново:

```bash
cd ~/PycharmProjects/manicure
docker compose down -v              # -v = удалить volumes (redis data)
rm -rf data backups                 # БД и бэкапы
docker image rm manicure-bot        # образ бота
```

Затем заново с Шага 6.

---

## Переход между маком и виндой

Если у тебя и мак, и виндовый десктоп:

- **Код** живёт в git, синхронизируется через `git pull` на обеих машинах.
- **Секреты** (`.env`, `license_private_key.pem`) — **не** в git.
  Храни в 1Password / Bitwarden / зашифрованной флешке.
- **Демо-бот** — отдельный на каждой машине (разные `BOT_TOKEN`,
  разные токены от BotFather). Можно иметь и один, если не планируешь
  показывать с двух машин одновременно.
- **Боевая БД клиентов** — никуда не таскай. Она на VPS клиента.
  Локально держать только бэкапы из TG-канала.

---

## Чек-лист одной шпаргалкой

```
□ Docker Desktop скачан с правильной ссылкой (arm64 для M1+)
□ Docker запущен, в меню-баре 🐳 не мигает
□ git --version работает
□ git clone прошёл
□ Демо-бот создан в BotFather, токен сохранён
□ user_id узнан через @userinfobot
□ .env заполнен, TENANT_SLUG=demo-nails
□ mkdir -p data backups
□ docker compose up -d --build прошёл
□ docker compose logs bot показывает "Бот запущен"
□ /start в TG работает, открывается админ-панель
□ ./scripts/reset_demo.sh отрабатывает за 15 сек
```

---

## Ссылки

- Архитектура проекта и правила: `CLAUDE.md`
- Плейбук продажи салонам: `docs/SALE_PLAYBOOK.md`
- Клиентская сторона: `docs/INSTALL.md`
- Восстановление БД: `docs/RESTORE.md`
- Лицензии: `docs/LICENSING.md`
