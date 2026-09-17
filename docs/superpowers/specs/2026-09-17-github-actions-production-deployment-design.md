# GitHub Actions and Production Deployment Design

Date: 2026-09-17
Status: Approved design, clarified
Repository: `Solvate-IT/ZAHLMEISTER`
Working branch: `development`
Production branch: `main`

## 1. Core rule

All implementation work is committed and pushed only to `development`.

GitHub Actions must **not run for `development`**. The workflow files may be prepared and tested there as normal repository files, but they become active only after the user manually merges the approved state to `main` and pushes `main`.

Only a push to `main` may trigger the automated CI/image/deployment pipeline.

## 2. Production workflow

A single `.github/workflows/production.yml` runs only on:

```yaml
on:
  push:
    branches: [main]
```

No `development` push trigger, no `pull_request` trigger and no `workflow_dispatch` trigger are used. A failed run can be re-run from GitHub without introducing a second activation path.

The workflow has three ordered phases:

1. **Validate** — run `docker/predeploy.sh` using the exact `main` commit.
2. **Build and publish** — publish the already validated backend/frontend runtime images to GHCR using immutable Git SHA tags.
3. **Deploy** — connect to Production over SSH and deploy those exact images.

Any failure in validation or image publication prevents the deploy phase from starting.

## 3. Image naming

Production images are immutable:

- `ghcr.io/solvate-it/zahlmeister-backend:<git-sha>`
- `ghcr.io/solvate-it/zahlmeister-frontend:<git-sha>`

Production never depends on `latest`.

The existing production Dockerfiles remain the source of truth:

- `docker/backend.Dockerfile`
- `docker/frontend.Dockerfile`

## 4. Production Compose integration

`docker/compose.prod.yml` keeps its existing `build:` definitions for local pre-deployment checks and emergency/manual builds.

The four runtime services gain transient image-repository overrides:

- backend image override for `bootstrap`, `backend`, `worker`;
- frontend image override for `frontend`;
- existing `IMAGE_TAG` remains the tag selector.

These deployment-only values are passed by the deployment process and are not added to `.env.development`, `.env.production` or `.env`.

## 5. Server-side deployment

A dedicated `docker/scripts/deploy-production.sh` contains all operational logic. The GitHub workflow only orchestrates SSH and credentials.

The script must:

1. require `ENVIRONMENT=production`;
2. require a full 40-character Git SHA;
3. require the server checkout to be clean, on `main`, and exactly at the requested SHA;
4. capture the currently running backend/worker/frontend images for application rollback;
5. pull both new images before touching running application containers;
6. create a PostgreSQL backup using the existing backup script;
7. run `bootstrap` with the new backend image and abort on failure;
8. replace worker, then backend;
9. wait for backend container health and `/api/v1/ready`;
10. replace frontend only after backend readiness;
11. verify frontend and the public `/api/v1/ready` route;
12. roll back application images when backend/frontend startup verification fails;
13. never automatically restore a database backup.

## 6. Downtime strategy

No Kubernetes, Swarm or blue/green stack is introduced.

GitHub performs the expensive build before deployment. Production pulls the finished images before replacing containers. The running release therefore remains available during build and download, and normal interruption is limited to the short container replacement/readiness window.

## 7. Failure behaviour

Before service replacement, failures in GitHub validation, image build/push, SSH, pull, backup or bootstrap leave the currently running application untouched.

If the new backend fails readiness, backend and worker are restored to the previously recorded application image where possible. Frontend is not changed until backend readiness passes.

If the new frontend fails verification, frontend is restored to its previously recorded image.

Database rollback is intentionally manual. Migrations must therefore remain production-safe and backward-compatible with the immediately previous application release whenever practical.

## 8. Security

Application credentials remain only on the production server in the existing `.env` / `docker/secrets` model.

GitHub Actions needs only deployment infrastructure secrets:

- `PRODUCTION_SSH_HOST`
- `PRODUCTION_SSH_PORT`
- `PRODUCTION_SSH_USER`
- `PRODUCTION_SSH_KEY`
- `PRODUCTION_SSH_KNOWN_HOSTS`

The workflow receives `contents: read` and `packages: write` only. SSH host verification is mandatory. `StrictHostKeyChecking=no` is forbidden. GHCR login uses `--password-stdin`, and the remote server logs out from GHCR after deployment.

## 9. Production checkout

The production host uses `/opt/ZAHLMEISTER` as the tracked checkout.

The workflow updates that checkout to the exact pushed `main` SHA using a fast-forward-only operation. A dirty checkout aborts deployment instead of overwriting local changes.

Application runtime code comes from immutable GHCR images; the checkout supplies tracked Compose files, scripts and production configuration.

## 10. Development behaviour

`development` remains the exclusive branch where ChatGPT makes and pushes changes.

No GitHub Action is triggered by pushes to `development`. Development verification is performed through the existing local/project commands, especially:

```bash
bash docker/predeploy.sh
```

and the `manage.sh` test/pre-deployment options.

The user manually decides when a verified `development` state is merged to `main`. That `main` push is the only event that activates GitHub CI, image publication and Production deployment.

## 11. Expected repository changes

Implementation should remain focused on:

- `.github/workflows/production.yml`
- `docker/compose.prod.yml`
- `docker/scripts/deploy-production.sh`
- deployment regression tests under `docker/scripts/`
- `docker/predeploy.sh`
- `docker/manage.sh` only to include the regression tests under the existing Tests entry
- `docker/OPERATIONS.md`

No `.github/workflows/ci.yml` is required.

## 12. Required tests

Regression checks must verify at least:

- exactly one production workflow exists for this feature;
- it triggers on `main` push only;
- it has no `development`, `pull_request` or `workflow_dispatch` activation path;
- production concurrency uses `cancel-in-progress: false`;
- GHCR image references use the immutable commit SHA;
- deployment script rejects non-production configuration and invalid SHAs;
- dirty Production checkout is rejected;
- image pull/bootstrap failure occurs before service replacement;
- backend startup failure invokes backend/worker rollback;
- frontend startup failure invokes frontend rollback;
- Compose retains local `build:` definitions;
- shell syntax and existing `docker/predeploy.sh` remain valid.

## 13. Final release sequence

The intended lifecycle is:

`development work`
→ local/pre-deployment verification
→ assistant pushes only to `development`
→ user manually merges/pushes to `main`
→ GitHub Action starts
→ production-equivalent checks
→ immutable GHCR images
→ SSH Production
→ pull images
→ database backup
→ bootstrap/migrate
→ worker/backend replacement
→ backend readiness
→ frontend replacement
→ public readiness
→ deployment complete.

No GitHub Action executes merely because `development` was pushed.
