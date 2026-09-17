# GitHub Actions and Production Deployment Design

Date: 2026-09-17
Status: Approved design, implementation pending
Repository: `Solvate-IT/ZAHLMEISTER`
Working branch: `development`
Production branch: `main`

## 1. Goals

ZAHLMEISTER shall have a fully automated CI/CD path with these properties:

- every push to `development` is validated by production-equivalent checks;
- every push/merge to `main` is validated before any production change occurs;
- backend and frontend production images are built once in GitHub Actions and pushed to GitHub Container Registry (GHCR);
- production deploys exactly the images built for the corresponding `main` commit;
- the production server no longer spends deployment time compiling application images;
- application downtime during normal releases is reduced to the short container replacement window;
- failed validation, image build, registry push, migration/bootstrap, startup or health checks stop the deployment;
- application secrets remain on the production server and are never copied into GitHub Actions;
- deployments are serialized so two production releases cannot run at the same time;
- the existing Docker/Compose architecture remains intact. No Kubernetes, Swarm, Redis, deployment platform or additional proxy layer is introduced.

## 2. Current Architecture to Preserve

The existing production stack already provides the required basis:

- PostgreSQL 17 remains a persistent local Docker volume;
- `bootstrap`, `backend` and `worker` use the same backend production image;
- `frontend` uses its own nginx-based production image;
- only the frontend is connected to the external Traefik proxy network;
- nginx proxies `/api/` requests internally to the backend service;
- the backend exposes `/api/v1/ready` and has a Docker healthcheck;
- `docker/predeploy.sh` builds the actual production Dockerfiles, runs backend and frontend tests, validates the schema bootstrap and performs a production-runtime smoke test;
- `.env.production` contains non-secret production configuration while secrets remain in the ignored `.env` and `docker/secrets/production` structure.

The deployment solution shall extend these structures rather than create an independent deployment stack.

## 3. Workflow Split

### 3.1 Development CI

A workflow such as `.github/workflows/ci.yml` runs on:

- push to `development`;
- pull requests targeting `main`.

It shall:

1. check out the repository with full enough history for repository checks;
2. execute `bash docker/predeploy.sh` with a unique CI image tag;
3. fail immediately when any check fails;
4. never push production images;
5. never contact the production server.

This workflow is the regular development quality gate.

### 3.2 Production workflow

A separate `.github/workflows/production.yml` runs only for a push to `main`.

It shall use a fixed production concurrency group with `cancel-in-progress: false`. A later production release waits for the current one instead of cancelling a running deployment midway.

The workflow has three ordered phases:

1. **Validate** — run the same production-equivalent checks as development.
2. **Build and publish** — build the final backend and frontend runtime images and publish them to GHCR using immutable commit tags.
3. **Deploy** — connect to the production host over SSH, pull the exact images, run production bootstrap/migration and replace services in a controlled order.

No deploy job may run if validation or image publication fails.

## 4. Image Naming and Immutability

Images shall use lowercase GHCR names:

- `ghcr.io/solvate-it/zahlmeister-backend:<git-sha>`
- `ghcr.io/solvate-it/zahlmeister-frontend:<git-sha>`

The Git commit SHA is the deployment identity. Production must not depend on a mutable `latest` tag.

Optional convenience tags such as `main` may be published for inspection, but the deployment script must always receive and use the immutable SHA tag.

The workflow shall build from the existing production Dockerfiles:

- `docker/backend.Dockerfile`
- `docker/frontend.Dockerfile`

The same runtime stages validated by `predeploy.sh` are therefore the ones published and deployed.

## 5. Production Compose Integration

`docker/compose.prod.yml` shall keep its existing `build:` definitions for local pre-deployment checks and emergency/manual builds.

The image references shall become registry-aware through environment variables, for example:

- `BACKEND_IMAGE` with a safe local default;
- `FRONTEND_IMAGE` with a safe local default;
- `IMAGE_TAG` remains usable for local builds where appropriate.

The automated production deployment will export explicit GHCR image references containing the commit SHA before invoking Compose.

This preserves the existing local operational path while allowing production to use prebuilt images without maintaining a second Compose file.

## 6. Production Deployment Script

A dedicated script under `docker/scripts/`, for example `deploy-production.sh`, shall contain all server-side deployment logic. The GitHub workflow should remain orchestration only and not duplicate operational shell logic inline.

The script must:

1. verify it is running in `ENVIRONMENT=production`;
2. verify the repository checkout is on `main` and matches the requested deployment commit;
3. validate layered ENV configuration and environment parity using the existing ENV helpers;
4. record the currently running backend and frontend image references for rollback;
5. pull the requested backend and frontend images before stopping any running application container;
6. create a database backup before schema-changing bootstrap/migration work;
7. run `bootstrap` with the new backend image and abort on any failure;
8. start or recreate the worker with the new backend image;
9. replace the backend with the new backend image;
10. wait until the backend container is healthy and `/api/v1/ready` succeeds;
11. replace the frontend only after backend readiness is confirmed;
12. verify the frontend container and the public application endpoint;
13. print a concise success summary containing the deployed commit/image tag;
14. remove only obsolete deployment resources that are safe to remove; persistent data must never be deleted.

The time-consuming image download happens before service replacement, so users continue using the old release during that phase.

## 7. Downtime Strategy

ZAHLMEISTER will not introduce full blue/green infrastructure at this stage.

The expected normal deployment interruption is therefore limited to the actual replacement of the single backend/frontend service containers. This should be a short window because:

- images are already built in GitHub;
- images are already pulled before replacement;
- migrations/bootstrap happen before frontend replacement;
- backend readiness is verified before the frontend is switched;
- the existing frontend remains available for as long as possible.

This is intentionally simpler than introducing duplicate production stacks or an orchestrator.

If future load or availability requirements demand effectively zero-downtime application swaps, a later design can introduce parallel backend/frontend candidates behind Traefik. That is explicitly outside the current scope.

## 8. Failure and Rollback Behaviour

### Before service replacement

Failures in CI, image build, GHCR push, SSH connection, image pull, backup or bootstrap must leave the currently running application untouched.

### During backend replacement

If the new backend fails startup or readiness after replacement, the deployment script shall attempt an application-image rollback to the previously recorded backend/worker image and verify readiness again.

### During frontend replacement

If the new frontend fails to start or the public health check fails, the script shall restore the previously recorded frontend image.

### Database caveat

Application rollback cannot automatically undo an arbitrary destructive database migration. Therefore migrations introduced into ZAHLMEISTER must remain production-safe and backward-compatible with the immediately previous application release whenever practical.

The deployment creates a database backup before bootstrap/migration, but database restoration is a separate emergency operation and must not be executed automatically by CI/CD.

This avoids turning a recoverable application failure into an automatic destructive database action.

## 9. Health Checks

The deployment shall use layered verification:

- Docker container running state;
- backend Docker healthcheck;
- backend `/api/v1/ready` response;
- frontend container HTTP response;
- frontend-to-backend proxy request where practical;
- final public HTTPS check against `PUBLIC_APP_URL` or its configured health endpoint.

Readiness loops shall use explicit timeouts and fail with useful logs rather than hanging indefinitely.

## 10. GitHub and Server Credentials

Application secrets remain exclusively on the server.

GitHub Actions requires only deployment infrastructure credentials:

- production SSH host;
- SSH port;
- SSH user;
- SSH private key;
- pinned SSH host key / known-hosts entry.

The workflow receives `packages: write` permission only for publishing GHCR images and the minimum `contents: read` permission required to check out the repository.

For production image pulls, the workflow may pass its short-lived GitHub token over the encrypted SSH session to `docker login ghcr.io --password-stdin`; the credential must never be written into the repository or command output. The remote host shall execute `docker logout ghcr.io` after the pull/deploy operation.

No Mollie, SMTP, Ponto, database, application-secret or other business credential is stored as a GitHub Actions secret solely for deployment.

## 11. Production Checkout Behaviour

The production host remains a Git checkout at the established project path (currently expected as `/opt/ZAHLMEISTER`).

Before deployment the workflow shall update that checkout to the exact `main` commit being deployed. It must not deploy arbitrary uncommitted server-side source changes.

The checkout is required for Compose files, scripts and tracked production configuration; application runtime code itself comes from the immutable GHCR images.

A dirty production checkout must stop deployment with a clear error rather than silently overwrite local changes.

## 12. Backup Behaviour

The existing dedicated backup script remains the source of truth for PostgreSQL backups.

The production deployment script shall invoke it before bootstrap/migration and fail the deployment if the backup fails.

Backups stay outside Git and are never uploaded as GitHub Actions artifacts by default.

## 13. Security Controls

The implementation must ensure:

- GitHub workflow permissions follow least privilege;
- third-party actions are avoided where a simple shell command or official Docker/GitHub action suffices;
- external actions that are used are pinned to immutable commit SHAs where practical;
- SSH host verification is mandatory; `StrictHostKeyChecking=no` is forbidden;
- secrets are never echoed;
- GHCR authentication uses `--password-stdin`;
- the production deploy script refuses non-production ENV configuration;
- production workflow deployment is restricted to `main`;
- production compose security settings (`read_only`, dropped capabilities, non-root UID, secret mounts) remain unchanged.

## 14. Repository Files Expected to Change

Implementation is expected to touch or add only a small number of deployment-focused files:

- `.github/workflows/ci.yml` — development/PR validation;
- `.github/workflows/production.yml` — main validation, image publication and deploy;
- `docker/compose.prod.yml` — registry-aware image references while retaining build definitions;
- `docker/scripts/deploy-production.sh` — server-side controlled deployment and rollback;
- deployment-focused shell tests under `docker/scripts/`;
- `docker/predeploy.sh` only if required to make image validation reusable without duplicating logic;
- `docker/OPERATIONS.md` — operator documentation and required GitHub secrets.

Existing application code should not need changes for this CI/CD work unless a concrete deployment-health issue is discovered.

## 15. Testing Strategy

Implementation shall be test-driven where behaviour changes are introduced.

At minimum, tests/checks shall cover:

- workflow files exist and are branch-scoped correctly;
- production workflow cannot deploy from `development`;
- production deployment concurrency does not cancel an in-progress release;
- GHCR image references include the immutable commit tag;
- deployment script rejects non-production configuration;
- deployment script aborts before service replacement when pull/bootstrap fails;
- backend failure invokes application-image rollback logic;
- frontend failure invokes frontend rollback logic;
- dirty production checkout is rejected;
- shell syntax validation for all deployment scripts;
- `docker compose config` succeeds with representative production image variables;
- existing `docker/predeploy.sh` remains successful.

The GitHub workflows themselves shall use the same repository scripts that operators can run locally wherever possible.

## 16. Deployment Sequence Summary

The final production path is:

`push/merge main`
→ GitHub production-equivalent validation
→ build backend/frontend production images
→ publish immutable GHCR SHA images
→ SSH production host
→ verify clean main checkout and exact commit
→ pull images
→ database backup
→ bootstrap/migrate using new backend image
→ update worker
→ update backend
→ wait for backend readiness
→ update frontend
→ public health check
→ logout from GHCR
→ deployment successful.

Any failure before the service replacement stage leaves the running release unchanged. Failures during replacement trigger application-image rollback where safe.

## 17. Non-Goals

This design intentionally does not introduce:

- Kubernetes;
- Docker Swarm;
- a second reverse proxy;
- a permanent staging cluster;
- Redis/Kafka/RabbitMQ;
- duplicate blue/green production stacks;
- automatic database restore;
- deployment directly from `development`;
- mutable `latest` as the production release identifier.
