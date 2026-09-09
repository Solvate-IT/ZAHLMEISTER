# Zahlmeister production operations

## Runtime architecture

The production server runs PostgreSQL, FastAPI/worker and an Nginx container containing the static Next.js export. Traefik remains the single external reverse proxy. The iOS/Android applications use the same React UI through Capacitor and call the same FastAPI API; no second application backend exists.

## Production start

1. Copy `.env.production.example` to `.env.production` and set host/domain/provider IDs.
2. Set `APP_RUNTIME_UID`/`APP_RUNTIME_GID` to the non-root account that owns the application secrets (defaults to `10001:10001`).
3. Run `ZM_ENV_FILE=./.env.production ./scripts/generate-secrets.sh` once. If the current user does not match the runtime UID/GID, run it as root so ownership can be set without making secrets world-readable.
4. Add `secrets/production/platform_smtp_password` if required and keep it owned by the same runtime UID/GID with mode `0640` (directory mode `0750`).
5. Add optional Ponto certificates under `secrets/ponto/` with the same restrictive permissions.
6. Run `./predeploy.sh` with the intended production environment.
7. Run `./manage.sh --production`, then start the stack.

Secret files are mounted read-only under `/run/secrets`. Never commit real files under `secrets/`.
The database backup does not include the application secret or provider certificates; back them up separately in an encrypted secret store. Without the original `APP_SECRET`, encrypted customer provider configurations cannot be decrypted after restore.

## Database schema

Zahlmeister currently uses a fresh-schema model. SQLAlchemy metadata is the single schema source of truth; `app.db.bootstrap` creates missing schema objects idempotently. There is no Alembic revision history in this pre-production baseline. Schema evolution for an existing production database must be introduced deliberately before the first production upgrade that changes persisted structures.

## Production build checks

`./predeploy.sh` builds the actual production Dockerfiles, runs backend lint/tests and Next.js type checking, builds the final backend/frontend images and inspects their runtime contents. It also verifies that the Capacitor source and app-link templates are present and that Flutter/Dart runtime references are gone.

Native apps are built from `mobile/` because Android/iOS are store artifacts rather than production Docker images:

```bash
../mobile/tool/bootstrap_mobile.sh app.example.com https://app.example.com/api/v1
```

The script builds the same Next.js source with the native API base, synchronizes Capacitor and creates Android plus, on macOS, iOS projects. Android Studio/Xcode then perform signing/store builds. Publish the association files described in `mobile/mobile-links/` before enabling verified HTTPS app links.

## Backup / restore

Manual backup:

```bash
ZM_ENV_FILE=./.env.production ZM_COMPOSE_FILE=./compose.prod.yml ./scripts/backup.sh
```

Backups are PostgreSQL custom-format dumps, verified with `pg_restore -l` and accompanied by a SHA-256 file. Default retention is 30 days (`BACKUP_RETENTION_DAYS`).

Recommended cron example:

```text
17 2 * * * cd /opt/ZAHLMEISTER/docker && ZM_ENV_FILE=./.env.production ZM_COMPOSE_FILE=./compose.prod.yml ./scripts/backup.sh >> /var/log/zahlmeister-backup.log 2>&1
```

Restore is deliberately destructive and requires `--force`. It creates a `pre_restore` safety backup, stops backend/worker/frontend, recreates the database, restores the dump, runs the idempotent schema bootstrap and starts the application again.

## Monitoring

- `/api/v1/health`: process liveness; does not touch the database.
- `/api/v1/ready`: database + production configuration + worker heartbeat.
- `/api/v1/health/metrics`: protected operational JSON via `X-Monitoring-Token`.
- `./scripts/ops-status.sh`: local operator view.

An external uptime service should check `/api/v1/ready`. Alert on HTTP != 200 and separately on failed jobs or excessive pending-job age.

## Logging

Backend and worker emit structured JSON to stdout in production. Every HTTP request receives an `X-Request-ID`; the same ID is present in backend request logs. Docker rotates container logs at 10 MB with five files by default. Secrets, request bodies and query strings are not written by the request logger.

## Rate limits

Nginx enforces per-IP limits before FastAPI:

- authentication/account actions: 10 requests/minute;
- contact form: 5 requests/minute;
- public payment reads/QR: 10 requests/second;
- online checkout creation: 20 requests/minute;
- customer API `/api/public/v1`: 20 requests/second;
- generic API: 50 requests/second;
- provider webhooks: 200 requests/second.

The public frontend is expected to be reachable through trusted Traefik, which must overwrite client forwarding headers rather than trust caller-supplied forwarding headers.

## Customer API

Customer API access is disabled per organization by default. When enabled, credentials are scoped and the raw API key is shown only once. External clients use `Authorization: Bearer <key>` against `/api/public/v1`. The FastAPI OpenAPI schema remains the source of truth for request/response contracts.

The production CORS list includes the public HTTPS host plus the fixed local Capacitor origins. Do not add wildcard origins.

## Retry strategy

PostgreSQL remains the only job queue. Failed transient jobs retry exponentially with jitter: 5 s, 10 s, 20 s ... up to 15 minutes, maximum seven attempts by default. HTTP 408/425/429/5xx, timeouts and transport errors are retryable. Configuration/validation errors fail immediately. Jobs left in `running` after a worker crash are recovered after 15 minutes.
