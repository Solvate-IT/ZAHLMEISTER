# Zahlmeister production operations

## Runtime architecture

Production runs PostgreSQL, FastAPI/worker and the static Next.js frontend in Docker. Traefik remains the single external reverse proxy. Android/iOS use the same React UI through Capacitor and the same FastAPI backend.

## Environment configuration

Tracked configuration lives in `.env.development` and `.env.production`. Both files must expose the same configuration keys and the same private-key markers; environment-specific values may differ.

The ignored `.env` contains only:

- `ENVIRONMENT=development` or `ENVIRONMENT=production`
- private/secret values whose keys are explicitly marked in both tracked environment files as `# KEY=  # set inside .env`

Normal configuration must not be duplicated in `.env`. The shared loader rejects unexpected active keys there.

The Docker scripts load `.env.${ENVIRONMENT}` first and `.env` second, so approved private values override the tracked configuration. Existing `*_FILE` secret mechanisms remain supported.

`manage.sh`, pre-deployment and maintenance scripts share `scripts/env.sh`. It fails when `.env.development` and `.env.production` have different key sets or private markers, or when `.env` contains non-private configuration.

## Production start

1. Set `ENVIRONMENT=production` and required private values in `.env`.
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
