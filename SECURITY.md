# Security

## Reporting a vulnerability

Please do **not** open a public GitHub issue for security problems.

Email: _set this up with your domain before first sale_
Telegram: [@plssog](https://t.me/RiobVO)

Include: reproducer or steps, affected version/commit, your Telegram/email
for follow-up. Expect first response within 72 hours.

## In scope

- Unauthenticated access to any admin function.
- SQL injection, RCE, SSRF, path traversal in the bot or its tools.
- Secrets leakage (tokens, license private key, customer PII) via bot
  responses or logs sent to external channels.
- License bypass on a deployment where enforcement is enabled.
- Backup exfiltration or tampering.

## Out of scope

- The Telegram platform itself.
- Self-inflicted footguns: committing `.env`, running as root in the
  container, exposing port 6379 to the public internet.
- Attacks requiring an already-compromised VPS root account.
- DoS by flooding Telegram updates — rate-limited by Telegram upstream.

## Secrets handling

- `.env` is gitignored. `.env.bak.*` too.
- `license_private_key.pem` is gitignored and only lives on the author's
  workstation.
- The public license key is committed on purpose and is not a secret.
- Customer PII (phone, name) is stored in the tenant's own DB and is
  **not** sent to error/backup channels. Check this before adding new
  fields to `utils/error_reporter.py`.

## If the worst happens

License private key leaked → regenerate via `tools/generate_keys.py`,
update `utils/license.py`, redeploy every paying tenant. All outstanding
licenses become invalid — brace for support calls.

Bot token leaked → revoke via `@BotFather` → `/revoke` → regenerate →
update `BOT_TOKEN` in `.env` → `docker compose up -d`.

Customer DB compromised on their VPS → scope is that single tenant, no
lateral impact (per-tenant isolation). Customer must notify their
clients per local law.
