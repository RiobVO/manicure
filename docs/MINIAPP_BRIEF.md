# 🎨 Telegram Mini App: «Beauty Studio» — Booking System

Промт-бриф для разработки Telegram Mini App, заменяющего callback-flow букинга
на полноценное мини-приложение с мгновенным откликом.

---

## 1. Context

Telegram-бот для записи в бьюти-салон (Узбекистан, маникюр + педикюр + лицо +
воск + шугаринг + уходовые процедуры). Сейчас работает на callback-кнопках —
каждый шаг букинга это `edit_message_text`, что упирается в rate-limit Telegram
(1 edit/сек на чат) и даёт 2-4с залипания на 8-9 тапе.

Mini App переносит весь UX на клиент: рендер локально на устройстве, без
round-trip на каждый тап. Бот участвует только при финале (получает финальный
JSON, пишет в БД, шлёт уведомления, напоминания).

**Целевой рынок:** бьюти-салоны Ташкента, 1-3 мастера, 30-100 записей в неделю.
Клиенты — женщины 18-45, в основном на мобильных, IPv4 интернет переменного
качества.

## 2. Goals

- **Отклик ≤ 50мс** на каждое нажатие (нативно-плавный UX).
- **Букинг за ≤ 6 тапов** от открытия до подтверждения (категория → услуга →
  мастер → дата → время → confirm).
- **Никаких "залипаний"** — UI отзывается мгновенно, network-операции идут
  в фоне с loading-индикатором.
- **Поддержка темы Telegram** (light/dark автоматически).
- **Двуязычность** RU + UZ.

## 3. Non-Goals (на этом этапе)

- Не делаем оплату внутри Mini App (платёж после букинга через Click/Payme
  deeplink, как сейчас).
- Не делаем профиль клиента (имя/телефон один раз тянутся из ботовой БД
  через initData).
- Не делаем чат с салоном (всё через основного бота).
- Не делаем PWA / standalone — только Telegram WebApp.

## 4. User Personas

### 4.1 Малика, 26, постоянная клиентка
- Знает каких мастеров любит, какие услуги делает.
- Хочет записаться за 30 секунд, желательно «как в прошлый раз».
- На iPhone, Telegram Desktop тоже.

### 4.2 Юлдуз, 34, новая клиентка
- Пришла по QR-коду на ресепшене.
- Не знает мастеров, нужны фото работ, рейтинги.
- Готова листать и сравнивать.

### 4.3 Камилла, владелица салона (admin)
- Mini App не использует — у неё админка в боте через reply-клавиатуру.
- Из требований: видеть запись от Mini App в админке мгновенно, как от
  обычного букинга.

## 5. User Flows

### Flow A: «Быстрая запись» (постоянная клиентка, 5 тапов)

```
[Открыла Mini App из бота]
  ↓
[Hero: «Привет, Малика!» + 2 кнопки: 'Повторить как в прошлый раз' / 'Новая запись']
  ↓ tap 'Новая запись'
[6 категорий — большие иконки в сетке 2×3]
  ↓ tap 'Маникюр'
[Список услуг с миниатюрами + ценами + длительностью]
  ↓ tap услугу
[Выбор мастера — карточки с фото, рейтингом, bio (опционально)]
  ↓ tap мастера
[Календарь 14 дней + слоты времени снизу]
  ↓ tap слот
[Bottom sheet: подтверждение — карточка-чек]
  ↓ tap MainButton 'Записаться' (нативная TG-кнопка)
[Success state + автозакрытие через 1.5с]
```

### Flow B: «Мои записи»
- Отдельная вкладка (TabBar внизу или меню в углу).
- Список ближайших + история. Свайп влево на карточке = меню (отменить /
  перенести / повторить).

### Flow C: Отзыв после визита
- Бот шлёт сообщение «оставь отзыв» с кнопкой → открывает Mini App в режиме
  `?action=review&appt=N`.
- Экран: 5 звёзд (большие, тапабельные) + textarea + кнопка «Отправить».

## 6. Screens (детально)

### 6.1 Home (categories)

**Layout:**
- Хедер: имя клиентки или «Привет 👋» (если нет профиля), под ним микро-копи
  «Запишись за минуту».
- Сетка **3 ряда × 2 колонки** = 6 категорий.
- Каждая карточка: эмодзи **large** (48px), название, под ним «N услуг»
  мелким текстом.
- Карточки **с лёгкой тенью**, скруглением 16px, hover/press-state
  с тактильной отдачей (`HapticFeedback.impactOccurred('light')`).

**Цвета карточек** (мягкие, по категориям, чтобы визуально различить):
- 💅 Маникюр — `#FFE5EC` (soft pink)
- 🦶 Педикюр — `#E8F5E9` (mint)
- 👁 Лицо — `#FFF3E0` (peach)
- 🪒 Воск — `#F3E5F5` (lavender)
- 🍯 Шугаринг — `#FFF9C4` (honey)
- ✨ Уходовые — `#E1F5FE` (sky)

В dark theme: те же тона с opacity 0.15 поверх `bg.secondary`.

### 6.2 Service list

- Список карточек, каждая 80-100px высоты.
- Слева: **миниатюра** (если есть `photo_file_id` в БД — показываем; иначе
  emoji-плейсхолдер).
- Справа: название (16px medium), под ним длительность + цена (14px,
  регулярный, серый).
- Tap по карточке → переход. Никаких чекбоксов, addons выбираются на
  следующем шаге.

### 6.3 Master picker

- Если мастер один — **пропускаем шаг автоматически**.
- Иначе: горизонтальный slider карточек 280px ширины.
- Карточка: фото мастера 240×240 со скруглением, под ним имя, рейтинг
  (звёзды + цифра), bio в 2 строки.
- Tap → выбран, MainButton `Далее` снизу.

### 6.4 Date + time

- Топ: **календарь** на 14 дней. Горизонтальный scroll: chip per day
  (Пн 5 / Вт 6 / ...).
- Текущий день выделен. Выходные — серые (disabled).
- Под календарём: **сетка свободных слотов времени** (3 колонки × 4-5 рядов).
- Slot button: 60×40, скругление 8, `bg.secondary` для свободных,
  `bg.primary` для выбранного.
- Если слотов нет — **empty state**: «На этот день мест нет. Выбери другой 📅».

### 6.5 Confirm

- Bottom sheet (не fullscreen, чтобы клиент видел контекст).
- Чек-карточка: услуга, мастер, дата, время, цена.
- Под ней: чекбокс «Оплатить онлайн через Click» (если PAYMENT_PROVIDER ≠ none).
- Внизу: TG **MainButton** «Записаться» (нативная, не кастомная) — это
  критично для быстрого отзыва.
- Tap → `WebApp.sendData(JSON.stringify({...}))` → бот ловит, пишет в БД,
  отвечает закрытием Mini App + сообщением в чате.

### 6.6 My appointments (вторая вкладка)

- TabBar внизу: 🏠 Home / 📋 Мои записи / 👤 Профиль.
- На вкладке 📋: ближайшая запись — карточка hero с countdown
  («Через 2 дня в 14:00»).
- Под ней: список будущих, потом — история (collapsed «Показать прошлые»).
- Каждая карточка: дата+время, услуга, мастер. Long-press / swipe = действия
  (отменить, перенести, повторить).

## 7. Design System

### Colors

```css
/* Берём из Telegram theme params, fallback на наши */
--bg-primary:     var(--tg-theme-bg-color, #FFFFFF);
--bg-secondary:   var(--tg-theme-secondary-bg-color, #F4F4F5);
--text-primary:   var(--tg-theme-text-color, #0F0F0F);
--text-secondary: var(--tg-theme-hint-color, #707579);
--accent:         var(--tg-theme-button-color, #FF6B9D);  /* фолбэк — soft pink */
--accent-text:    var(--tg-theme-button-text-color, #FFFFFF);
--destructive:    #EF4444;
```

**Категорийные пастели** см. выше — фиксированы (не из TG-темы), для
узнаваемости.

### Typography

- Системный стек: `-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Roboto', sans-serif`.
- Размеры: 12 (caption), 14 (body small), 16 (body), 18 (title small), 22 (title), 28 (display).
- Высота строки 1.4 для body, 1.2 для title.

### Spacing

- Шкала: 4, 8, 12, 16, 20, 24, 32, 48 (восьмёрка).
- Padding экранов 16px по бокам, 12px между карточками.

### Components

- **Button**: высота 44 (тач-таргет), скругление 12, font 16/medium.
- **Card**: 16 padding, 16 border-radius, тень
  `0 2px 8px rgba(0,0,0,0.04)` (light) / `0 2px 8px rgba(0,0,0,0.3)` (dark).
- **Input**: 48 высота, скругление 10, focus-ring 2px accent.

### Iconography

- Эмодзи как есть (TG их рендерит нативно — отзывчиво и легко).
- Линейные иконки от Lucide для функциональных (clock, calendar, star, x).

## 8. Interactions / Micro-UX

- **Haptic** на каждое действие (`HapticFeedback.impactOccurred('light')`).
- **Skeleton loaders** (1-2 колонки серых блоков) пока тянутся данные.
  Никаких спиннеров на 50% экрана.
- **Optimistic UI**: при тапе на дату — слоты появляются мгновенно (даже если
  ещё не пришли), потом обновляются с реальных. Клиент не должен «ждать».
- **Transitions**: 200мс slide для между экранами, ease-out. Не используем
  Telegram-ной нативной анимации.
- **BackButton** Telegram — навигация назад через TG (`WebApp.BackButton.show()`).
- **MainButton** — единственный CTA на каждом экране.
- **Show keyboard** для отзыва — `WebApp.expand()` чтобы не зажимало UI.
- **Pull-to-refresh** на «Мои записи».

## 9. Tech Stack

**Recommendation:**
- **React 18** + **Vite** (быстрый dev, маленький bundle ~80KB gzipped).
- **TypeScript** strict mode (защита от ошибок в interactions с TG SDK).
- **Tailwind CSS** + **shadcn/ui** (готовые primitives с хорошим UX).
- **@telegram-apps/sdk-react** или официальный `window.Telegram.WebApp`.
- **TanStack Query** для API-кэша (мгновенный обратный переход на ранее
  загруженный экран).
- **Wouter** для routing (1KB вместо react-router 30KB).

**Alternative for minimum bundle:**
- Vanilla TS + Tailwind, без React. Если bundle <40KB — заметно быстрее
  старт на слабых телефонах.

## 10. API Contract

Mini App должен общаться с ботом через два канала:

### 10.1 Read API (HTTPS endpoints на стороне бота)

Бот поднимает aiohttp-сервер с эндпоинтами (рядом с уже существующим payment
webhook):

```
GET  /api/categories             → [{key, label, emoji, count}]
GET  /api/services?category=KEY  → [{id, name, price, duration, photo_url}]
GET  /api/masters                → [{id, name, photo_url, bio, rating}]
GET  /api/slots?master_id=&date=&duration= → [{time}]
GET  /api/me                     → {user_id, name, phone, history: [...]}
GET  /api/my_appointments        → [{id, date, time, service, master, status}]
POST /api/cancel_appointment     {appt_id, reason} → {ok}
```

**Auth:** через `initData` Telegram (HMAC от бот-токена + user_id + timestamp).
Бот проверяет валидность и срок жизни (24ч).

### 10.2 Write — финал букинга через `WebApp.sendData()`

```js
WebApp.sendData(JSON.stringify({
  type: 'book',
  service_id: 42,
  master_id: 3,
  date: '2026-05-15',
  time: '14:00',
  addons: [],
  pay_online: true
}));
```

Бот ловит этот JSON в `message.web_app_data.data`, валидирует, создаёт
запись, шлёт подтверждение в чат, закрывает Mini App.

## 11. Integration с существующим ботом

- Кнопка «🌟 Открыть приложение» в reply-клавиатуре бота → запускает Mini App.
- Inline-кнопка в напоминаниях / приветствии → `WebApp` info с `start_param`
  (`?action=review&appt=N`).
- Существующий callback-flow остаётся — Mini App это **альтернатива**, не
  замена. Клиент может выбрать.
- Админка (от лица admin) — продолжает работать через callback-кнопки.
  Mini App только для клиентов.

## 12. Delivery Etaps

### Phase 1 — MVP (1 неделя)
- 6 категорий, список услуг, выбор мастера, дата/время, confirm.
- Чтение через initData, write через sendData.
- Без оплаты, без отзывов, без «мои записи».
- Без анимаций (instant render).

### Phase 2 — UX polish (3-4 дня)
- Skeleton loaders, transitions, haptic.
- Категорийные цвета, фото услуг и мастеров.
- Empty states.

### Phase 3 — Full features (1 неделя)
- «Мои записи» вкладка с действиями.
- Отзывы.
- Quick rebook («как в прошлый раз»).
- Двуязычие RU+UZ.

### Phase 4 — Production (3-4 дня)
- Hosting Mini App: статика на Cloudflare Pages / Vercel (бесплатно, CDN
  глобально).
- Регистрация Mini App у @BotFather (`/newapp`).
- Тестирование на 5+ устройствах: iPhone (3 ver), Android, Telegram Desktop.

**Итого: 3-4 недели от 0 до production.**

## 13. Acceptance Criteria

- ✅ Mini App открывается за ≤ 800мс на 4G.
- ✅ Любой тап отзывается за ≤ 50мс (haptic + visual).
- ✅ Букинг от Home до confirm проходится за ≤ 6 тапов.
- ✅ В dark theme и light theme выглядит одинаково чисто.
- ✅ Bundle ≤ 150KB gzipped (с React + shadcn).
- ✅ initData валидируется на бэке (HMAC), без неё API возвращает 401.
- ✅ Запись от Mini App неотличима в БД от записи через callback-flow
  (та же таблица `appointments`, тот же flow уведомлений).

## 14. Don'ts

- ❌ Не использовать кастомные кнопки вместо TG MainButton — нативная
  отзывается быстрее.
- ❌ Не делать сложные тени и градиенты — рендер замедлится.
- ❌ Не делать > 1 запроса к API на экран при первой загрузке (агрегируй).
- ❌ Не использовать iframe внутри Mini App — баги с initData и BackButton.
- ❌ Не блокировать UI на network — всегда optimistic с фолбеком.

---

**Что про webhook бота** (контекст для исполнителя):
> Mini App не требует webhook. Бот может оставаться в polling. Webhook нужен
> только для callback-режима, чтобы быстрее получать клики; в Mini App клики
> обрабатываются на клиенте, и боту приходит только финальный `web_app_data`
> через polling — это всего 1 событие на букинг, а не 6.
