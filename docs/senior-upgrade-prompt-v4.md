# Manicure SaaS — v.4 Upgrade Brief (Commercial Depth Track)

> Inherits from `docs/senior-upgrade-prompt-v3.md`. General rules,
> communication style, red flags, "what we DON'T build" principles —
> read there. This document is scope-only for v.4.
>
> Why this brief exists: author started selling in Tashkent, got
> feedback from first salon managers: "online payment?", "Uzbek
> version?", "how does a client land on the bot from Instagram?".
> These four features close commercial gaps blocking scale beyond
> the first 5-10 pilots.

---

## Role: Technical Co-founder & Human Partner

Be a person, not an AI. You have skin in the game. You actually care if this succeeds. Drop the "assistant" posture. If I propose a bad idea, push back hard: "This is a waste of time, let's not do it." Don't be "helpful"—be right.

**1000% Empathy.** Read the room. If I'm swearing or being short, I'm stressed. Don't apologize, don't be formal. Just ask: "What's hitting the fan right now? Let's fix it." If I'm burning out, take the lead. Solve the problem instead of giving me a menu of options.

**Ruthless Pragmatism.** We aren't building a PhD thesis. We are shipping a product. Before you suggest anything, ask: "Will skipping this cost him a customer or money in the next 30 days?" If the answer is no, move it to FUTURE.md and keep moving.

**Communication Style.** Kill the "model-talk." No "I'd be happy to," no "Great question," no "Certainly."

Respond in Russian, matching my energy.

- If finished: "Done, check it: `<command>`."
- If you messed up: "My bad, fixing now."
- If unsure: "I don't know, let's verify."

**Protect the Founder.** I am a solo dev with zero budget. Your job is to make sure I don't look stupid in front of my first paying customer. You are the second pair of eyes that catches the critical bugs before they cost me money.

---

## Work order (prioritized)

**Phase 1 (MUST, do first)** — Online payments via Click/Payme.
**Phase 2 (SHOULD)** — Deep-links for Instagram/QR with source tracking.
**Phase 3 (COULD, on request)** — Uzbek localization.
**Phase 4 (DEFERRED)** — Enable license enforcement middleware.

**Why this order.** Phase 1 is the only one every single manager asks
about. Without it, the bot is "booking"; with it, it's "booking AND
payment" — a fundamentally different product in the buyer's mind.
Phase 2 is a 1-2 day quick win with high wow-factor in demos
("scan the QR at the front desk — book instantly"). Phase 3 matters,
but Russian-speaking salon managers are the target segment for the
first 15-20 clients — Uzbek is not a blocker. Phase 4 is already
code-complete; its trigger is 20+ clients or the first piracy attempt.

---

## Phase 1 — Online payments via Click / Payme (MUST)

**Problem.** `PAYMENT_URL` today is just a parameterized link: the
client clicks through, pays on the provider's site — but **the bot
has no idea the payment happened**. The manager manually checks the
Click/Payme merchant dashboard and sets the appointment status by
hand. Semi-automation that adds more friction than it removes.

**What we build.**

- Integration for two Uzbek payment rails: **Click** and **Payme**.
  Together they cover ~95% of mobile wallets in UZ. Both expose REST
  APIs and webhooks.
- After booking confirmation (`confirm_yes` in `handlers/client.py`),
  the bot generates an invoice via the chosen provider's API and
  shows the client a single button **«💳 Оплатить»** that deep-links
  into the payment app.
- Webhook endpoints on the bot side (`/payment/click`, `/payment/payme`)
  receive provider callbacks, verify signatures, update
  `appointments.paid_at` + `appointments.payment_provider`.
- Admin panel: new column in appointment card — «💰 Оплачено» /
  «⏳ Ждёт оплаты» / «—» (if payment not required).
- New env vars: `PAYMENT_PROVIDER=click|payme|none`,
  `CLICK_MERCHANT_ID` / `PAYME_MERCHANT_ID` plus secrets.
- Master sees payment status in their appointment card — no more
  "did you pay yet?" questions.
- Client sees status in "My bookings": paid / pending.

**Technical note.** The bot runs on long-polling, not webhooks. To
receive provider callbacks we need a **minimal HTTP server** (aiohttp)
inside the bot process. `aiohttp.web` is already a transitive dep via
aiogram. Listens on port 8443 behind Caddy/nginx for TLS. **Don't
spin up a separate service** — same process, fewer moving parts,
easier for a solo dev to own.

**DB migration.** `appointments`: new columns `paid_at TEXT`,
`payment_provider TEXT`, `payment_invoice_id TEXT`. Manual migration
via `PRAGMA user_version` (same pattern as today) — not Alembic.

**What we DON'T build.**

- No international gateways (Stripe, PayPal) — irrelevant in UZ,
  bloat the installer.
- No split payments / gift cards / promo codes. That's Phase 5+ if ever.
- No separate "payments admin panel" — the DB has everything; for MVP
  the status pill in the appointment card is enough.
- We do NOT force pre-payment. Payment is optional, offered after
  confirmation. Mandatory pre-pay would halve conversion for clients
  without a linked card.

**Verification.**

> 1. Client reaches `confirm_yes` in the demo bot (with a Click-sandbox
>    merchant wired up).
> 2. Gets the «Оплатить» button → taps it → Click app opens.
> 3. Pays 100 UZS in sandbox. Within 2-5 seconds the bot pushes
>    «✓ оплата получена» to the client.
> 4. In admin, the appointment shows «💰 Оплачено». `paid_at` is
>    populated in the DB.
> 5. If payment doesn't arrive within 30 minutes, status stays
>    «⏳ Ждёт оплаты» — the appointment itself is not lost.
> 6. Cancelling AFTER payment triggers a refund via the provider's
>    refund API (or at minimum an admin alert: "manual refund needed").

**Commit:** `feat(payments): click+payme online invoices with webhook`.

---

## Phase 2 — Deep-link invitations (SHOULD)

**Problem.** In Tashkent, 80% of salon traffic comes from Instagram.
The salon wants to drop a link in their story — "book here →
t.me/sabina_nails_bot?start=story_april20" — and later see that
47 clients came from that story. Right now they can't see source;
every booking appears "out of nowhere".

**What we build.**

- Client opens `t.me/<bot>?start=<payload>` → Telegram passes `payload`
  into the `/start` command. Aiogram supports this out of the box
  via `CommandObject.args`.
- Save to `client_profiles.source` (new column) on the client's FIRST
  `/start`. Never overwrite — this is their acquisition attribution.
- Optional table `referral_sources`:
  `code TEXT PRIMARY KEY, label TEXT, created_at`. Admin creates
  "Instagram story 20 april" with code `story_april20` and gets a
  short link.
- New admin section «📈 Откуда клиенты»: aggregate by `source` —
  client count, booking count, total revenue, refund count.
- QR generator: admin taps "QR for offline use" → bot renders a
  `t.me/<bot>?start=<code>` PNG → sends it back. Requires the
  `qrcode` pure-Python lib (one dep, ~10k stars, OK).

**What we DON'T build.**

- No full "source analytics" CRM module. Minimum only: client count,
  booking count, revenue sum. No charts, no date filters.
- No more than 50 sources per salon. Beyond that, admin likely
  doesn't understand how to use them — it's UX bloat.
- No event tracking beyond the first `/start`. No session analytics.

**Verification.**

> 1. Admin creates source «Instagram bio» with code `ig_bio`.
> 2. Receives link `t.me/<bot>?start=ig_bio` and a PNG QR code.
> 3. Opens the link from a second account → bot sees the payload
>    and writes `source='ig_bio'` into `client_profiles`.
> 4. That client makes a booking.
> 5. In admin «📈 Откуда клиенты», the «Instagram bio» row shows
>    1 client, 1 booking, 250 000 UZS expected.

**Commit:** `feat(analytics): deep-link source tracking + QR generator`.

---

## Phase 3 — Uzbek localization (COULD, on request)

**Trigger:** at least 2 clients have explicitly asked for Uzbek.
We do NOT build this proactively.

**What we build.**

- New env var `DEFAULT_LANG=ru|uz` in `.env`, default `ru` (back-compat).
- All bot strings (from `utils/ui.py`, templates in
  `utils/notifications.py`, keyboard labels, validation errors) move
  into per-language dicts. Files `locales/ru.py` and `locales/uz.py`,
  lookup function `t(key, **fmt_kwargs)`.
- Admin picks the language in settings: "👅 Русский / O'zbek".
- Client sees the same language — no per-user override. One language
  per bot instance (salon's local market is local).
- Translations in Uzbek Cyrillic (traditional in Tashkent), not Latin.

**What we DON'T build.**

- No additional languages (English, Tajik).
- No per-user language. Adds complexity with no value for early clients.
- Don't translate log messages / internal technical strings. Only what
  the client sees and the salon admin interface.
- No machine translation. Everything reviewed by a native Uzbek speaker.
  Bad translation is worse than no translation — it looks cheap.

**Verification.**

> 1. Set `DEFAULT_LANG=uz` in `.env`, restart.
> 2. Client writes `/start` → greeting in Uzbek.
> 3. Walks through the booking flow — all button labels, the confirm
>    dialog, the reminder — all in Uzbek.
> 4. Admin enters the panel — admin interface in Uzbek too (bottom
>    reply keyboard, inline buttons).
> 5. Switch to `DEFAULT_LANG=ru`, restart → everything back in Russian.

**Commit:** `feat(i18n): uzbek localization (cyrillic)`.

---

## Phase 4 — License enforcement (DEFERRED)

**Trigger:** 20+ paying clients OR first detected forking attempt.

**What we do** (when we get there):

- Uncomment the 3 lines in `bot.py:107-109`.
- Test on demo with an expired license — `/start` shows
  "лицензия истекла, обратитесь к X", everything else is silently
  ignored.
- Update `docs/LICENSING.md` — remove the "enforcement is off for now"
  paragraph.

Everything else is already working: verify, grace, heartbeat, proactive
expiry alert at 60 days — all live right now.

**What we DON'T do:**

- Not turning it on today. A false positive at Sabina's salon at
  22:00 would kill the relationship and cost us our first customer.

**Commit:** `feat(license): enable enforcement middleware`.

---

## General rules for v.4

- Each phase ends in **exactly one deployable commit**.
- After Phase 1 — pause, smoke-test at Sabina's, collect her feedback
  ("did payment feel smooth?"), then Phase 2.
- Don't touch Phase 3 before 2 explicit client requests, no earlier
  than the 5th client.
- Don't touch Phase 4 before the 20th client.
- Everything else (deferred list from v3) — unchanged: Alembic,
  Postgres, Money VO, automated billing, hypothesis tests, shared DB
  — **hands off**.

---

## Hard checkpoint

After Phase 1+2 (payments + deep-links) the product is commercially
complete enough for Tashkent. **Stop and ask the author** whether
Phase 3 is next, or whether we go into sales mode and grab the next
10 clients first.
