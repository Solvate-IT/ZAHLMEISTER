# Zahlmeister operations

## Runtime architecture

Production runs PostgreSQL, FastAPI/worker and the static Next.js frontend in Docker. Traefik remains the single external reverse proxy. Android/iOS use the same React UI through Capacitor and the same FastAPI backend.

## Configuration model

Configuration is intentionally split into three layers:

1. `docker/.env` is ignored by Git and contains only `ENVIRONMENT=development|production` plus real credentials for external services that are actually enabled.
2. `docker/.env.development` contains Development-specific runtime/deployment configuration.
3. `docker/.env.production` contains Production-specific runtime/deployment configuration.

Technical defaults such as PostgreSQL database/user names, worker retry values, provider API URLs/scopes and internal secret paths live in code or Compose instead of being exposed as user configuration.

The tracked Development and Production files have the same key set and the same external-credential markers. `scripts/env.sh` validates this before Docker operations.

### Internal secrets

Zahlmeister creates and persists its own internal secrets automatically under `docker/secrets/<environment>/`:

- PostgreSQL password
- backend database URL derived from that password
- `APP_SECRET`
- platform-admin bootstrap password
- monitoring token

These values are not configuration and do not belong in `.env`. Existing values are never rotated automatically.

For backward compatibility, when an older `.env` still contains one of these internal keys, Zahlmeister adopts that value into the internal secret store on first start. This preserves existing database credentials, encrypted configuration and the platform-admin login. The obsolete keys can then be removed from `.env`.

Production internal secrets are owned/readable by the existing non-root runtime user `10001:10001`. Initialization therefore runs as root (or directly as that runtime user). Secret values are never printed by the helper scripts.

### External credentials

External provider credentials remain in the ignored `docker/.env`, for example:

```env
ENVIRONMENT=development
MOLLIE_BILLING_API_KEY=test_...
# MICROSOFT365_CLIENT_ID=...
# MICROSOFT365_CLIENT_SECRET=...
# PONTO_CONNECT_CLIENT_ID=...
# PONTO_CONNECT_CLIENT_SECRET=...
```

Only keys explicitly marked as `external credential in .env` in the tracked environment files are accepted. Normal configuration duplicated into `.env` is rejected.

Provider certificates/private keys that are inherently files, such as Ponto mTLS material, remain under the ignored `docker/secrets/ponto/` directory.

## Production start

1. Set the real production values in `.env.production` and keep its key set synchronized with `.env.development`.
2. Create `docker/.env` with `ENVIRONMENT=production` and only the external credentials that are used.
3. Run `./predeploy.sh`.
4. Run `./manage.sh` and choose **Start**.

Internal secrets are initialized automatically before Compose starts. Never commit `.env`, certificates, private keys or generated files under `secrets/`.

## manage.sh

The standard menu intentionally contains only frequent operations:

1. Start — starts the existing stack without building.
2. Stop.
3. Clean Build — removes containers/orphans, rebuilds without cache and starts again; persistent volumes are retained.
4. Status.
5. Logs.
6. Pre-Deployment Checks.
7. Backend Shell.
8. Frontend Shell.
9. Database Initialize / Migrate / Verify.
10. Tests.

Use `q` to quit. Backup, restore and other uncommon maintenance tasks remain separate scripts under `scripts/`.

## Database schema

Schema initialization remains idempotent. Existing production data must be considered before schema changes; incompatible changes require explicit safe migrations.

## Pre-deployment checks

`./predeploy.sh` validates environment parity, Git tracking and Docker Compose, builds the actual production Dockerfiles, runs backend lint/tests and frontend build checks, inspects final runtime images and performs production-style smoke tests. Important runtime files are checked with `git ls-files` so local untracked files cannot hide packaging errors.
