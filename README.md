# Manicure Bot

A Telegram booking bot for beauty salons. Self-hosted, per-salon VPS, no
multi-tenant shenanigans. Built to be sold and supported by one person.

> [!NOTE]
> This is a commercial product, not an open-source project. The source is
> visible so customers can audit it and contractors can extend it — but
> deployment requires a license key. See [LICENSE.md](LICENSE.md).

---

## What it does

Clients book manicure appointments through a Telegram conversation. Salon
owners run everything from an admin panel inside the same bot — services,
masters, schedule, blocked time, statistics, reviews.

**Client flow:** service → add-ons → master → date → time → confirm.
Reminders fire 24 h and 2 h before the visit. Cancel or reschedule
inline. One tap to leave a review after.

**Admin flow:** a single live-editing panel message per chat. CRUD for
services and add-ons. Per-master schedules and blocked slots. Appointments
list with status changes, reschedule, cancellation with reason. Stats
dashboard and Excel export. Multiple admins via `.env` or runtime-added
through the panel.

## Who it's for

One beauty salon, one bot, one VPS. That's the whole model. No shared
databases, no tenant isolation layer, no paranoia about neighbour leaks —
every salon gets its own deployment, its own admin, its own data.

Trade-offs behind that choice are discussed below under
[Architecture decisions](#architecture-decisions).

## Architecture at a glance

```
                   Telegram Bot API
                          │
                  ┌───────┴────────┐
                  │    aiogram 3    │
                  └───────┬────────┘
           ┌──────────────┼──────────────┐
           │              │              │
     FSMGuard*       Routers (14)    Error reporter
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
    SQLite (WAL)      APScheduler         Redis
    single connection  reminders 15m     FSM storage
    BEGIN IMMEDIATE    backup 6h          persistent
    PRAGMA FK=ON       heartbeat 24h      across restarts
        │                 │
    manicure.db    ./backups/   ───→   Telegram channel
                   (7 rolling)          (every 6h)
```

\* FSMGuard was removed; persistent Redis storage made it unnecessary.

## Install in one command

On a fresh Ubuntu VPS:

```bash
git clone https://github.com/RiobVO/manicure.git
cd manicure
./install.sh <tenant_slug> <bot_token> <admin_telegram_id>
```

The installer prompts optionally for the backup channel, error channel,
license key, heartbeat URL and support contact — press Enter to skip
anything that isn't set up yet. Target time on a 1 GB droplet with
Docker pre-installed: **under 5 minutes** end to end.

Updates and uninstalls: `./scripts/update.sh`, `./scripts/uninstall.sh`.
The uninstaller archives `data/` and `backups/` to `/root/` before
removing anything — data loss is opt-in, not default.

Customer-facing version of this guide: [docs/INSTALL.md](docs/INSTALL.md).
Restoring from a backup: [docs/RESTORE.md](docs/RESTORE.md).

## What ships with the product

- **State that survives restarts.** FSM in Redis; a client mid-booking
  picks up exactly where they left off after a redeploy.
- **Off-site backups.** Every 6 h the DB copies itself into a private
  Telegram channel the owner controls. RPO = 6 h, RTO = one file
  download + `cp`.
- **Remote triage.** `/status` returns tenant, uptime, DB size, last
  backup timestamp, Redis ping, last unhandled error. Unhandled
  exceptions push to an error channel with tenant tag and short
  traceback — support without SSH.
- **Offline license verification.** Ed25519-signed keys, 90-day grace,
  daily heartbeat. Enforcement is **active** — without `LICENSE_KEY`
  the bot runs in `restricted` mode and replies only to `/start`
  (see [docs/LICENSING.md](docs/LICENSING.md)).

## Pricing and licensing

Per-salon annual license, paid yearly. Installation and first-month
support included. See [LICENSE.md](LICENSE.md) for terms. Contact
[@plssog](https://t.me/RiobVO) for pricing.

## Roadmap

What's scoped but not shipped is in [FUTURE.md](FUTURE.md). Short list
of things deliberately deferred until a concrete trigger fires:

- Alembic migrations (at ~5 tenants)
- Postgres (at ~20 masters per tenant or >500 ms booking latency)
- Fleet dashboard (at ~30 tenants)
- i18n (at first non-Russian customer)
- Sentry (at ~20 tenants, when grouping beats push-to-phone)

## What I'd do differently

- Started with per-tenant VPS from day one (did this — still right).
- Did NOT start with Alembic. Manual `PRAGMA user_version` migrations
  are fine at one-digit tenant counts. Alembic would have eaten weeks.
- Did NOT touch the existing booking logic during the commercial-readiness
  pass. Symmetric overlap check with a write-lock was hundreds of hours
  of UX tuning; "refactoring while I'm here" is how products die.
- Shipped license enforcement **enabled by default** (after a tested
  signing/verify pipeline). The "off until 20 customers" hedge created
  doc/code drift — every install ends up needing a key anyway, so make
  the missing key fail loud at install-time, not silent at first booking.

## Stack

- Python 3.12
- [aiogram 3.7](https://github.com/aiogram/aiogram)
- aiosqlite (SQLite WAL, FK=ON)
- APScheduler (interval jobs)
- Redis 7 (FSM storage)
- cryptography (Ed25519 license signing)
- Docker Compose v2

## Repository layout

```
bot.py                   entrypoint
config.py                .env reader
constants.py             business constants
scheduler.py             reminders, backup, heartbeat jobs
states.py                FSM states
install.sh               one-command tenant installer
scripts/                 update.sh, uninstall.sh
docker-compose.yml       redis + bot, tenant-parametric
Dockerfile               python:3.12-slim, non-root
.env.template            install.sh fills this in
db/                      SQLite layer (connection, tables, queries)
handlers/                aiogram routers (client, admin_*, reviews, status)
keyboards/inline.py      all inline & reply keyboards
services/booking.py      free-slot calculation
utils/                   panel, admin, license, heartbeat, error_reporter, ...
middlewares/             license_gate (active — enforces RESTRICTED mode)
tools/                   generate_keys, issue_license (author-only CLIs)
tests/                   86+ real integration tests (not stubs)
docs/                    LICENSING.md, INSTALL.md, RESTORE.md
```

## Architecture decisions

- **Single global SQLite connection + `write_lock` + `BEGIN IMMEDIATE`.**
  Atomic overlap check on booking, zero race windows in practice at
  salon scale. Migrating to Postgres later is a straight swap.

- **Per-tenant VPS instead of multi-tenant.** Isolation beats elegance
  at this scale. A bug in one salon can't leak into another's data. Each
  customer's billing is simple. Failure domains are clean. Multi-tenant
  is a reasonable rewrite after 100+ customers — not before.

- **Manual migrations via `PRAGMA user_version`.** Works at one-digit
  tenant counts. Replace with Alembic when a migration needs to be
  reversible or multi-step.

- **License public key hardcoded in the source (`utils/license.py`).**
  Not in a file beside the binary. Tampering requires a code change
  that shows up in `git diff`. This is speed-bump DRM, not a vault.

- **Error channel over Sentry.** A solo founder with a phone in hand
  doesn't need event grouping at ten tenants — he needs the push. Swap
  to Sentry when group dedup starts mattering.

## Contact

- Sales / support: [@plssog](https://t.me/RiobVO)
- Security: see [SECURITY.md](SECURITY.md)
- Issues: open a GitHub issue (public repo) or DM the Telegram handle above
