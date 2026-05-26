# Changelog

Notable changes. Semantic versioning starts at 1.0.0 = first paid license.
Dates are local (Asia/Tashkent).

## [Unreleased]

Reserve for the next wave of changes.

## [1.0.0] — TBD (first paid license)

First commercially-sellable release. One-command install, per-tenant VPS
isolation, offline license verification (enforcement active — `LICENSE_KEY`
required for production), off-site backups, remote triage.

### Added

- `install.sh` — one-command installer for a fresh Ubuntu VPS. Takes
  `tenant_slug`, `bot_token`, `admin_id`. Prompts optionally for backup
  channel, error channel, license key, heartbeat URL, support contact.
  Target deploy time: under 5 minutes.
- `Dockerfile` + `docker-compose.yml` with `bot` and `redis` services.
  Container names, Redis volume, and log tags are parametrised by
  `TENANT_SLUG` so multiple tenants can coexist on one host.
- `scripts/update.sh` — `git pull` + `docker compose up -d --build`.
- `scripts/uninstall.sh` — archives `data/`, `backups/`, `.env` to
  `/root/` before removing the deployment directory. Never silent.
- **FSM in Redis** — client booking state survives bot restarts. Falls
  back to `MemoryStorage` if `REDIS_URL` is unset or Redis is unreachable.
- **Off-site backups.** `backup_db` is now called every 6 h (RPO) and,
  when `BACKUP_CHAT_ID` is set, the `.db` file is pushed to a private
  Telegram channel with a `[tenant] backup TIMESTAMP • SIZE` caption.
  Local rotation (7 files) unchanged.
- **Centralized error reporting.** Unhandled exceptions in handlers and
  scheduler jobs are forwarded to `ERROR_CHAT_ID` with tenant tag, short
  context and traceback. Sending failures are swallowed — alerting never
  crashes the bot.
- **`/status` admin command.** Returns tenant slug, uptime, DB size,
  last backup timestamp, live Redis ping and last seen error.
- **Offline license verification.** Ed25519-signed license tokens with
  `tenant_slug`, `customer_name`, `license_id`, `issued_at`, `expires_at`.
  Public key hardcoded in `utils/license.py`. Evaluator picks one of four
  modes: `dev` / `ok` / `grace` / `restricted`. Grace period 90 days.
- **Heartbeat.** Once-per-24h POST to `HEARTBEAT_URL` (+ one fire on
  startup). Payload: `{tenant_slug, license_id, version, last_seen}`.
  Failure is telemetry-only, never blocks the bot.
- **Author CLI tools.** `tools/generate_keys.py` (one-time keypair
  generation), `tools/issue_license.py` (per-sale license signing, with
  `--expires-at` override for testing grace/restricted).
- **Documentation.** `docs/LICENSING.md`, `docs/INSTALL.md`, `docs/RESTORE.md`,
  `LICENSE.md` (commercial), `SECURITY.md`, `FUTURE.md`.

### Changed

- Backup frequency 24 h → 6 h.
- `GRACE_DAYS` 7 → 90 to match production SaaS norms.
- `scheduler.py` jobs wrapped with `_safe_send_reminders` and
  `_safe_run_backup` — crashes there now hit the error channel instead
  of silently killing a job.
- Migrated dev dependency list: `redis==5.2.1`, `cryptography==43.0.3`.

### Removed

- `middlewares/fsm_guard.py` (`FSMGuardMiddleware`). It invalidated FSM
  state on every restart via a per-process UUID — no-op with
  `MemoryStorage`, actively harmful with Redis. No tests referenced it.

### Preserved deliberately

- SQLite + WAL + single global connection + `BEGIN IMMEDIATE` — correct
  for single-tenant scale, untouched.
- Manual `PRAGMA user_version` migrations — works at one-digit tenant
  counts, untouched.
- Booking logic with symmetric overlap check and write-lock — hundreds
  of hours of UX tuning, untouched.
- 86+ existing integration tests — untouched, still pass.
