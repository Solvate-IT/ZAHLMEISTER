# Zahlmeister production operations

## Runtime architecture

Production runs PostgreSQL, FastAPI/worker and the static Next.js frontend in Docker. Traefik remains the single external reverse proxy. Android/iOS use the same React UI through Capacitor and the same FastAPI backend.

## Environment configuration

Tracked configuration lives in `.env.development` and `.env.production`. Both files must expose the same configuration keys; environment-specific values may differ. Secrets and installation-specific overrides belong only in the ignored `.env`.

`.env` must contain:

```env
ENVIRONMENT=development
```

or:

```env
ENVIRONMENT=production
```

The Docker scripts load `.env.${ENVIRONMENT}` first and `.env` second, so private values override the tracked defaults. Secret keys remain documented in both tracked environment files as comments such as `# MOLLIE_BILLING_API_KEY=  # set inside .env`. Existing `*_FILE` secret mechanisms remain supported.

`manage.sh`, pre-deployment and maintenance scripts share `scripts/env.sh`, which also fails when `.env.development` and `.env.production` have different key sets.

## Production start

1. Set `ENVIRONMENT=production` and production-specific private values in `.env`.
2. Configure required secret files under `secrets/production/` where `*_FILE` is used.
3. Run `./predeploy.sh`.
4. Run `./manage.sh` and choose **Start**.

Secret files are mounted read-only under `/run/secrets`. Never commit `.env`, certificates, keys or files under `secrets/`.

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

Use `q` to quit. Backup, restore, secret generation and other uncommon maintenance tasks remain separate scripts under `scripts/`.

## Database schema

Zahlmeister currently uses an idempotent SQLAlchemy bootstrap as the schema source of truth. Existing production data must be considered before future schema changes; migration support must be introduced before production upgrades that require data transformations or incompatible constraints.

## Pre-deployment checks

`./predeploy.sh` validates environment parity, Git tracking and Docker Compose, builds the actual production Dockerfiles, runs backend lint/tests and frontend build checks, inspects final runtime images and performs production-style smoke tests. Important runtime files are checked with `git ls-files` so local untracked files cannot hide packaging errors.

## Native apps

Native apps are built from `mobile/` because Android/iOS are store artifacts rather than production Docker images:

```bash
../mobile/tool/bootstrap_mobile.sh app.example.com https://app.example.com/api/v1
```

Android Studio/Xcode handle signing and store builds.

## Backup / restore

Maintenance scripts remain available under `scripts/backup.sh` and `scripts/restore.sh`. They use the same layered ENV logic as the main Docker workflow. Restore is destructive and requires `--force`.

## Monitoring

- `/api/v1/health`: process liveness.
- `/api/v1/ready`: database, production configuration and worker heartbeat.
- `/api/v1/health/metrics`: protected operational metrics.
- `scripts/ops-status.sh`: local operational status.

Production backend/worker logs use structured JSON. Secrets, request bodies and sensitive credentials must never be logged.
