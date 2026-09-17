# GitHub Actions Production Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore GitHub Actions so `development` receives production-equivalent CI and every successful `main` push publishes immutable production images to GHCR and automatically deploys them to the ZAHLMEISTER production server with backup, health checks and safe application rollback.

**Architecture:** Reuse `docker/predeploy.sh` as the single production-equivalent validation path. The production workflow reuses the runtime images produced by that validation job, retags them with the immutable Git commit SHA, pushes them to GHCR, then updates the production checkout over SSH and invokes one server-side deployment script. The deployment script pulls images before touching running services, backs up PostgreSQL, runs bootstrap, replaces worker/backend/frontend in order, verifies readiness, and rolls application images back on startup failure.

**Tech Stack:** GitHub Actions, Docker Engine, Docker Compose v2, GHCR, Bash, SSH, PostgreSQL 17, FastAPI/Uvicorn, nginx/Next.js static export, Traefik.

**Spec:** `docs/superpowers/specs/2026-09-17-github-actions-production-deployment-design.md`

## Global Constraints

- Repository is exclusively `Solvate-IT/ZAHLMEISTER`.
- Working/default development branch is `development`; production deployment runs only from `main`.
- Do not add Kubernetes, Docker Swarm, Redis, Kafka, RabbitMQ or another reverse proxy.
- Preserve existing `docker/.env.development` / `docker/.env.production` layered ENV model and server-only application secrets.
- Production images must use immutable Git SHA tags; deployment must never depend on mutable `latest`.
- `docker/compose.prod.yml` must retain `build:` definitions so local pre-deployment and emergency builds still work.
- Time-consuming image build/pull must happen before running production containers are replaced.
- Database restore must never be automatic; only application-image rollback is automatic.
- Existing production security options, non-root UID, read-only root filesystem and secret mounts remain unchanged.
- Third-party actions must be avoided where shell commands suffice; `actions/checkout` remains pinned to an immutable commit SHA.
- Production SSH host verification is mandatory; `StrictHostKeyChecking=no` is forbidden.

---

## File Structure

- Create `.github/workflows/ci.yml` — development and main-PR validation only.
- Create `.github/workflows/production.yml` — `main` validation, GHCR publish and automated SSH deployment.
- Modify `docker/compose.prod.yml` — allow transient deployment image repository overrides while preserving local image defaults and `build:` blocks.
- Create `docker/scripts/deploy-production.sh` — all server-side deployment, readiness and rollback logic.
- Create `docker/scripts/deploy-production.test.sh` — deterministic shell regression tests using mocked command functions; no live production access.
- Create `docker/scripts/ci-cd-config.test.sh` — static CI/workflow/Compose safety assertions.
- Modify `docker/predeploy.sh` — require and run the deployment regression checks, and keep final image names compatible with GHCR retagging.
- Modify `docker/manage.sh` — include CI/CD shell regression tests under menu option 10 without changing the menu structure.
- Modify `docker/OPERATIONS.md` — document GitHub secrets, production server prerequisites, automated deployment flow and emergency/manual path.

---

### Task 1: Add failing CI/CD configuration regression tests

**Files:**
- Create: `docker/scripts/ci-cd-config.test.sh`
- Test: `.github/workflows/ci.yml`
- Test: `.github/workflows/production.yml`
- Test: `docker/compose.prod.yml`

**Interfaces:**
- Consumes: repository files as plain text.
- Produces: executable shell test returning non-zero when branch scoping, immutable tags, concurrency, GHCR names, SSH host verification or Compose image overrides are missing.

- [ ] **Step 1: Create the failing static regression test**

Create `docker/scripts/ci-cd-config.test.sh` with checks equivalent to:

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CI="$ROOT/.github/workflows/ci.yml"
PROD="$ROOT/.github/workflows/production.yml"
COMPOSE="$ROOT/docker/compose.prod.yml"

[[ -f "$CI" ]]
[[ -f "$PROD" ]]

grep -q 'branches: \[development\]' "$CI"
grep -q 'pull_request:' "$CI"
grep -q 'branches: \[main\]' "$CI"
! grep -q 'deploy-production.sh' "$CI"

grep -q 'push:' "$PROD"
grep -q 'branches: \[main\]' "$PROD"
! grep -q 'branches: \[development\]' "$PROD"
grep -q 'cancel-in-progress: false' "$PROD"
grep -q 'packages: write' "$PROD"
grep -q 'ghcr.io/solvate-it/zahlmeister-backend:${{ github.sha }}' "$PROD"
grep -q 'ghcr.io/solvate-it/zahlmeister-frontend:${{ github.sha }}' "$PROD"
grep -q 'known_hosts' "$PROD"
! grep -q 'StrictHostKeyChecking=no' "$PROD"
grep -q 'deploy-production.sh' "$PROD"

grep -Fq 'image: ${DEPLOY_BACKEND_IMAGE:-zahlmeister-backend}:${IMAGE_TAG:-latest}' "$COMPOSE"
grep -Fq 'image: ${DEPLOY_FRONTEND_IMAGE:-zahlmeister-frontend}:${IMAGE_TAG:-latest}' "$COMPOSE"

echo "CI/CD configuration checks passed."
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
bash docker/scripts/ci-cd-config.test.sh
```

Expected: FAIL because `.github/workflows/ci.yml` and `.github/workflows/production.yml` do not yet exist and Compose still uses fixed local image names.

- [ ] **Step 3: Commit the failing regression test**

```bash
git add docker/scripts/ci-cd-config.test.sh
git commit -m "test: define CI deployment safeguards"
git push origin development
```

---

### Task 2: Make Production Compose registry-aware without breaking local builds

**Files:**
- Modify: `docker/compose.prod.yml`
- Test: `docker/scripts/ci-cd-config.test.sh`

**Interfaces:**
- Consumes: transient shell variables `DEPLOY_BACKEND_IMAGE`, `DEPLOY_FRONTEND_IMAGE`, and existing `IMAGE_TAG`.
- Produces: image references for `bootstrap`, `backend`, `worker`, and `frontend` while retaining all existing `build:` definitions.

- [ ] **Step 1: Extend the failing test for all backend services**

Add assertions:

```bash
[[ "$(grep -Fc 'image: ${DEPLOY_BACKEND_IMAGE:-zahlmeister-backend}:${IMAGE_TAG:-latest}' "$COMPOSE")" -eq 3 ]]
[[ "$(grep -Fc 'image: ${DEPLOY_FRONTEND_IMAGE:-zahlmeister-frontend}:${IMAGE_TAG:-latest}' "$COMPOSE")" -eq 1 ]]
grep -q '^    build:$' "$COMPOSE"
```

- [ ] **Step 2: Run the test and verify the Compose assertions fail**

```bash
bash docker/scripts/ci-cd-config.test.sh
```

Expected: FAIL on image override assertions.

- [ ] **Step 3: Change only the four production image declarations**

Use exactly:

```yaml
bootstrap:
  image: ${DEPLOY_BACKEND_IMAGE:-zahlmeister-backend}:${IMAGE_TAG:-latest}

backend:
  image: ${DEPLOY_BACKEND_IMAGE:-zahlmeister-backend}:${IMAGE_TAG:-latest}

worker:
  image: ${DEPLOY_BACKEND_IMAGE:-zahlmeister-backend}:${IMAGE_TAG:-latest}

frontend:
  image: ${DEPLOY_FRONTEND_IMAGE:-zahlmeister-frontend}:${IMAGE_TAG:-latest}
```

Do not remove or alter the existing `build:` sections. `DEPLOY_*` variables are ephemeral deployment controls, not persistent application configuration, so they must not be added to `.env.development`, `.env.production`, or `.env` where `env.sh` would intentionally normalize them.

- [ ] **Step 4: Validate Compose and confirm the relevant static checks now pass**

Run:

```bash
cd docker
DEPLOY_BACKEND_IMAGE=ghcr.io/solvate-it/zahlmeister-backend \
DEPLOY_FRONTEND_IMAGE=ghcr.io/solvate-it/zahlmeister-frontend \
IMAGE_TAG=0123456789abcdef \
docker compose --env-file .env.production -f compose.prod.yml config -q
cd ..
```

If a private `.env` is required by local ENV tooling, use the existing project mechanism rather than inventing alternate configuration.

Then run:

```bash
bash docker/scripts/ci-cd-config.test.sh
```

Expected: workflow-file checks still fail, but Compose image assertions pass.

- [ ] **Step 5: Commit**

```bash
git add docker/compose.prod.yml docker/scripts/ci-cd-config.test.sh
git commit -m "feat: allow immutable production image references"
git push origin development
```

---

### Task 3: Implement the production deployment script with rollback

**Files:**
- Create: `docker/scripts/deploy-production.sh`
- Create: `docker/scripts/deploy-production.test.sh`
- Existing dependency: `docker/scripts/backup.sh`
- Existing dependency: `docker/scripts/common.sh`

**Interfaces:**
- Command: `DEPLOY_BACKEND_IMAGE=<repo> DEPLOY_FRONTEND_IMAGE=<repo> IMAGE_TAG=<sha> ./docker/scripts/deploy-production.sh <sha>`
- Consumes: production `.env`/secrets through `common.sh`, existing running Compose stack, already authenticated Docker daemon for GHCR.
- Produces: running `worker`, `backend`, and `frontend` at the requested SHA or exits non-zero after restoring the previous application image where safe.

- [ ] **Step 1: Write tests for pure validation and rollback helpers before the script exists**

Create `docker/scripts/deploy-production.test.sh` that sources the deployment script without running `main` and tests these functions:

```bash
require_production_environment production
! require_production_environment development

require_sha 0123456789abcdef0123456789abcdef01234567
! require_sha latest
! require_sha abc123

old='ghcr.io/solvate-it/zahlmeister-backend:abc123'
[[ "$(image_repository "$old")" == 'ghcr.io/solvate-it/zahlmeister-backend' ]]
[[ "$(image_tag "$old")" == 'abc123' ]]
```

The test must also override shell functions to simulate deployment sequencing:

```bash
EVENTS=""
record(){ EVENTS+="$1\n"; }
pull_images(){ record pull; }
backup_database(){ record backup; }
run_bootstrap(){ record bootstrap; }
replace_worker(){ record worker; }
replace_backend(){ record backend; }
wait_backend_ready(){ record ready; return 0; }
replace_frontend(){ record frontend; }
wait_frontend_ready(){ record frontend_ready; return 0; }
public_health_check(){ record public; return 0; }

run_deployment
[[ "$EVENTS" == $'pull\nbackup\nbootstrap\nworker\nbackend\nready\nfrontend\nfrontend_ready\npublic\n' ]]
```

Add explicit failure cases:

```bash
# Bootstrap failure: backend/frontend replacement must never happen.
# Backend readiness failure: rollback_backend_stack must be invoked, frontend must not change.
# Frontend readiness failure: rollback_frontend must be invoked.
```

- [ ] **Step 2: Run the test and verify RED**

```bash
bash docker/scripts/deploy-production.test.sh
```

Expected: FAIL because `deploy-production.sh` does not exist.

- [ ] **Step 3: Implement `deploy-production.sh` as sourceable functions plus guarded `main`**

The script must begin with:

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

require_production_environment() {
  [[ "$1" == "production" ]] || {
    echo "Production deployment requires ENVIRONMENT=production." >&2
    return 1
  }
}

require_sha() {
  [[ "$1" =~ ^[0-9a-f]{40}$ ]] || {
    echo "Deployment tag must be a full 40-character Git SHA." >&2
    return 1
  }
}

image_repository() { printf '%s' "${1%:*}"; }
image_tag() { printf '%s' "${1##*:}"; }
```

The actual runtime setup belongs in `main`, after functions are defined:

```bash
main() {
  local requested_sha="${1:-}"
  require_sha "$requested_sha"

  source "$SCRIPT_DIR/common.sh"
  require_production_environment "$ENVIRONMENT"

  [[ "$(git -C "$DOCKER_DIR/.." branch --show-current)" == "main" ]] || {
    echo "Production checkout must be on main." >&2
    exit 1
  }
  [[ "$(git -C "$DOCKER_DIR/.." rev-parse HEAD)" == "$requested_sha" ]] || {
    echo "Production checkout does not match requested commit." >&2
    exit 1
  }
  [[ -z "$(git -C "$DOCKER_DIR/.." status --porcelain)" ]] || {
    echo "Production checkout contains local changes." >&2
    exit 1
  }

  : "${DEPLOY_BACKEND_IMAGE:?DEPLOY_BACKEND_IMAGE is required}"
  : "${DEPLOY_FRONTEND_IMAGE:?DEPLOY_FRONTEND_IMAGE is required}"
  export IMAGE_TAG="$requested_sha"

  capture_previous_images
  run_deployment
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
```

Implement the operational functions with the existing `compose()` helper from `common.sh`:

```bash
pull_images() {
  docker pull "${DEPLOY_BACKEND_IMAGE}:${IMAGE_TAG}"
  docker pull "${DEPLOY_FRONTEND_IMAGE}:${IMAGE_TAG}"
}

backup_database() {
  "$SCRIPT_DIR/backup.sh" >/dev/null
}

run_bootstrap() {
  compose run --rm --no-deps bootstrap
}

replace_worker() {
  compose up -d --no-deps --force-recreate worker
}

replace_backend() {
  compose up -d --no-deps --force-recreate backend
}

replace_frontend() {
  compose up -d --no-deps --force-recreate frontend
}
```

`capture_previous_images` must inspect existing containers without failing on first installation:

```bash
container_image() {
  local service="$1" id
  id="$(compose ps -q "$service")"
  [[ -n "$id" ]] || return 0
  docker inspect -f '{{.Config.Image}}' "$id"
}

capture_previous_images() {
  PREVIOUS_BACKEND_IMAGE="$(container_image backend || true)"
  PREVIOUS_WORKER_IMAGE="$(container_image worker || true)"
  PREVIOUS_FRONTEND_IMAGE="$(container_image frontend || true)"
}
```

Use explicit bounded readiness loops. Backend readiness must inspect both container health and `/api/v1/ready`; frontend readiness must verify `/` and its `/api/v1/ready` proxy from inside the frontend container. On timeout, print service logs before returning non-zero.

Implement rollback using the previously captured image reference. Because ZAHLMEISTER registry names do not contain an explicit port, split repository/tag with `image_repository` / `image_tag`, temporarily export those values, recreate the affected service(s), and restore the requested deployment variables afterward. Refuse digest-only previous references rather than guessing.

`run_deployment` must be exactly ordered:

```bash
run_deployment() {
  pull_images
  backup_database
  run_bootstrap
  replace_worker
  replace_backend
  if ! wait_backend_ready; then
    rollback_backend_stack
    return 1
  fi
  replace_frontend
  if ! wait_frontend_ready; then
    rollback_frontend
    return 1
  fi
  public_health_check
}
```

`public_health_check` must use the already loaded `PUBLIC_APP_URL`, append `/api/v1/ready`, use `curl --fail --silent --show-error --max-time 10`, and fail the deployment if the public endpoint is not ready. Do not disable TLS verification.

- [ ] **Step 4: Run the shell tests until GREEN**

```bash
bash -n docker/scripts/deploy-production.sh docker/scripts/deploy-production.test.sh
bash docker/scripts/deploy-production.test.sh
```

Expected: all cases pass, including sequencing, pre-replacement abort and rollback invocation.

- [ ] **Step 5: Commit**

```bash
git add docker/scripts/deploy-production.sh docker/scripts/deploy-production.test.sh
git commit -m "feat: add safe production image deployment"
git push origin development
```

---

### Task 4: Add development CI and fully automated main deployment workflows

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/production.yml`
- Test: `docker/scripts/ci-cd-config.test.sh`

**Interfaces:**
- Development CI consumes repository contents only.
- Production publish uses built local images `zahlmeister-backend:ci-${GITHUB_SHA}` and `zahlmeister-frontend:ci-${GITHUB_SHA}` created by `docker/predeploy.sh`.
- Production deploy requires GitHub secrets: `PRODUCTION_SSH_HOST`, `PRODUCTION_SSH_PORT`, `PRODUCTION_SSH_USER`, `PRODUCTION_SSH_KEY`, `PRODUCTION_SSH_KNOWN_HOSTS`.
- Production server repository path is `/opt/ZAHLMEISTER`.

- [ ] **Step 1: Extend static tests for exact workflow safety properties**

Require:

```bash
grep -q 'bash docker/predeploy.sh' "$CI"
grep -q 'bash docker/predeploy.sh' "$PROD"
grep -q 'needs: validate_publish' "$PROD"
grep -q 'git status --porcelain' "$PROD"
grep -q 'git merge --ff-only' "$PROD"
grep -q 'docker login ghcr.io' "$PROD"
grep -q 'docker logout ghcr.io' "$PROD"
grep -q '/opt/ZAHLMEISTER' "$PROD"
```

- [ ] **Step 2: Run tests and verify RED**

```bash
bash docker/scripts/ci-cd-config.test.sh
```

Expected: FAIL because workflows are absent.

- [ ] **Step 3: Create `.github/workflows/ci.yml`**

Use this structure:

```yaml
name: CI

on:
  push:
    branches: [development]
  pull_request:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  predeploy:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    steps:
      - name: Check out repository
        uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
        with:
          fetch-depth: 0
      - name: Run production-equivalent checks
        env:
          IMAGE_TAG: ci-${{ github.sha }}
        run: bash docker/predeploy.sh
```

No deploy command, registry push or production secret may appear in this workflow.

- [ ] **Step 4: Create `.github/workflows/production.yml`**

The workflow must be `push` to `main` plus optional manual re-run, with fixed production concurrency:

```yaml
name: Production

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  packages: write

concurrency:
  group: zahlmeister-production
  cancel-in-progress: false
```

The first job `validate_publish` must:

1. checkout pinned `actions/checkout`;
2. run `IMAGE_TAG=ci-${{ github.sha }} bash docker/predeploy.sh`;
3. login to GHCR using `GITHUB_TOKEN` via `--password-stdin`;
4. retag the exact validated runtime images:

```bash
docker tag "zahlmeister-backend:ci-${GITHUB_SHA}" "ghcr.io/solvate-it/zahlmeister-backend:${GITHUB_SHA}"
docker tag "zahlmeister-frontend:ci-${GITHUB_SHA}" "ghcr.io/solvate-it/zahlmeister-frontend:${GITHUB_SHA}"
docker push "ghcr.io/solvate-it/zahlmeister-backend:${GITHUB_SHA}"
docker push "ghcr.io/solvate-it/zahlmeister-frontend:${GITHUB_SHA}"
```

The second job `deploy` must `needs: validate_publish`, then create `~/.ssh/known_hosts` from `PRODUCTION_SSH_KNOWN_HOSTS`, create the private key with mode 600, and never disable host checking.

Update the remote checkout before invoking the repository deployment script:

```bash
ssh -p "$SSH_PORT" "$SSH_USER@$SSH_HOST" \
  "cd /opt/ZAHLMEISTER && \
   test -z \"\$(git status --porcelain)\" && \
   git fetch origin main && \
   git checkout main && \
   git merge --ff-only '$GITHUB_SHA' && \
   test \"\$(git rev-parse HEAD)\" = '$GITHUB_SHA'"
```

Authenticate the server to GHCR without placing the token in a command-line argument:

```bash
printf '%s' "$GHCR_TOKEN" | \
  ssh -p "$SSH_PORT" "$SSH_USER@$SSH_HOST" \
  "docker login ghcr.io -u '$GHCR_USER' --password-stdin"
```

Deploy:

```bash
ssh -p "$SSH_PORT" "$SSH_USER@$SSH_HOST" \
  "cd /opt/ZAHLMEISTER && \
   DEPLOY_BACKEND_IMAGE=ghcr.io/solvate-it/zahlmeister-backend \
   DEPLOY_FRONTEND_IMAGE=ghcr.io/solvate-it/zahlmeister-frontend \
   IMAGE_TAG='$GITHUB_SHA' \
   ./docker/scripts/deploy-production.sh '$GITHUB_SHA'"
```

Add a final `if: always()` logout step:

```bash
ssh -p "$SSH_PORT" "$SSH_USER@$SSH_HOST" 'docker logout ghcr.io >/dev/null 2>&1 || true'
```

Use job-level `env` for secret-derived values so GitHub masks them and shell commands stay readable.

- [ ] **Step 5: Run static tests and YAML sanity checks**

```bash
bash docker/scripts/ci-cd-config.test.sh
```

Expected: PASS.

Also inspect both workflow files for accidental `development` deploy triggers and unpinned non-GitHub actions.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/ci.yml .github/workflows/production.yml docker/scripts/ci-cd-config.test.sh
git commit -m "ci: restore automated production pipeline"
git push origin development
```

---

### Task 5: Integrate deployment safeguards into normal project checks and operator documentation

**Files:**
- Modify: `docker/predeploy.sh`
- Modify: `docker/manage.sh`
- Modify: `docker/OPERATIONS.md`
- Test: `docker/scripts/ci-cd-config.test.sh`
- Test: `docker/scripts/deploy-production.test.sh`

**Interfaces:**
- `manage.sh` option 10 continues to be the single user-facing test action.
- `predeploy.sh` fails if deployment scripts/workflows are missing or syntactically invalid.
- Documentation gives non-IT operators one normal rule: merge to `main`; GitHub performs deployment automatically.

- [ ] **Step 1: Add required deployment files to `predeploy.sh` required files**

Add:

```bash
".github/workflows/ci.yml"
".github/workflows/production.yml"
"docker/scripts/deploy-production.sh"
"docker/scripts/deploy-production.test.sh"
"docker/scripts/ci-cd-config.test.sh"
```

Add `.github/workflows` to the `runtime_paths`/tracked-input check so an untracked workflow cannot affect local expectations without being in GitHub.

- [ ] **Step 2: Run CI/CD shell regressions during predeploy validation**

In the existing script-validation stage, after `bash -n`, run:

```bash
"$SCRIPT_DIR/scripts/ci-cd-config.test.sh"
"$SCRIPT_DIR/scripts/deploy-production.test.sh"
```

Do not increase the numbered predeploy stage count merely for these small static tests; keep them part of the existing validation stage.

- [ ] **Step 3: Add deployment tests to `manage.sh` option 10**

Extend `run_tests()` to:

```bash
run_tests() {
  compose run --rm backend pytest -q
  compose run --rm frontend sh -c 'npm ci --no-audit --no-fund && npm test && npm run typecheck'
  "$SCRIPT_DIR/scripts/platform-admin-access.test.sh"
  "$SCRIPT_DIR/scripts/ci-cd-config.test.sh"
  "$SCRIPT_DIR/scripts/deploy-production.test.sh"
}
```

Do not add a new menu entry; deployment remains automated and uncommon maintenance remains outside `manage.sh`.

- [ ] **Step 4: Document the normal production process for non-IT users**

Update `docker/OPERATIONS.md` with a section that says plainly:

```text
Normal production release:
1. Changes are developed and tested on development.
2. Merge the approved state to main.
3. GitHub Actions runs all checks, builds the exact production images and deploys automatically.
4. If any GitHub job fails, Production is not advanced (or the application image is rolled back if startup fails).
5. No server-side Docker build is required during a normal release.
```

Document the five repository secrets by exact name:

```text
PRODUCTION_SSH_HOST
PRODUCTION_SSH_PORT
PRODUCTION_SSH_USER
PRODUCTION_SSH_KEY
PRODUCTION_SSH_KNOWN_HOSTS
```

Document server prerequisites:

- `/opt/ZAHLMEISTER` is a clean Git checkout;
- production `.env` and `docker/secrets/production` already exist on the server;
- deploy user can run Docker without interactive sudo;
- deploy user can fetch the repository's `main` branch;
- `curl` is installed for the public readiness check;
- central Traefik network `solvate_proxy` exists.

Document emergency manual flow separately: checkout approved `main`, authenticate/pull the immutable images, invoke `deploy-production.sh <sha>`. Do not instruct users to rebuild Production routinely.

- [ ] **Step 5: Run focused checks**

```bash
bash -n docker/manage.sh docker/predeploy.sh docker/scripts/*.sh
bash docker/scripts/platform-admin-access.test.sh
bash docker/scripts/ci-cd-config.test.sh
bash docker/scripts/deploy-production.test.sh
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add docker/predeploy.sh docker/manage.sh docker/OPERATIONS.md docker/scripts
git commit -m "docs: integrate automated deployment safeguards"
git push origin development
```

---

### Task 6: Full verification before merging the CI/CD implementation

**Files:**
- Verify all modified files from Tasks 1–5.
- No new production code unless verification reveals a concrete defect.

**Interfaces:**
- Produces a verified `development` commit suitable for deliberate promotion to `main`.

- [ ] **Step 1: Verify branch and cleanliness**

```bash
git branch --show-current
git status --short
```

Expected: `development`, clean working tree.

- [ ] **Step 2: Run the project's complete local production-equivalent check**

From repository root with the normal Development selector in `docker/.env`:

```bash
IMAGE_TAG=verify-$(git rev-parse --short HEAD) bash docker/predeploy.sh
```

Expected: all 11 stages pass, including backend tests, frontend tests, PostgreSQL bootstrap, runtime image inspection, worker/backend readiness, frontend proxy smoke test, CI/CD configuration regressions and deployment-script tests.

- [ ] **Step 3: Verify immutable images produced by predeploy**

```bash
TAG="verify-$(git rev-parse --short HEAD)"
docker image inspect "zahlmeister-backend:${TAG}" >/dev/null
docker image inspect "zahlmeister-frontend:${TAG}" >/dev/null
```

Expected: both images exist locally and correspond to the code just verified.

- [ ] **Step 4: Re-read workflows for production-scope safety**

Confirm:

```bash
grep -n 'branches:' .github/workflows/*.yml
grep -n 'cancel-in-progress' .github/workflows/*.yml
grep -n 'ghcr.io/solvate-it/zahlmeister-' .github/workflows/production.yml
grep -n 'deploy-production.sh' .github/workflows/production.yml
```

Expected: `development` appears only in CI push scope; production deploy is `main` only; production concurrency uses `cancel-in-progress: false`; image paths use the commit SHA.

- [ ] **Step 5: Push final verified Development state**

```bash
git push origin development
```

Do not merge to `main` as part of implementation unless explicitly requested after verification.

- [ ] **Step 6: Configure GitHub repository secrets before the first Production run**

In GitHub repository settings, create exactly these Actions secrets:

```text
PRODUCTION_SSH_HOST=<production hostname or IP>
PRODUCTION_SSH_PORT=22
PRODUCTION_SSH_USER=<dedicated deploy user>
PRODUCTION_SSH_KEY=<private key corresponding to an authorized server key>
PRODUCTION_SSH_KNOWN_HOSTS=<pinned known_hosts line for the production server>
```

The known-hosts value must be verified out-of-band before storing it; do not populate it by calling `ssh-keyscan` blindly inside the workflow.

- [ ] **Step 7: First controlled Production activation**

After the user explicitly approves promotion to `main`, merge/push the verified `development` state to `main`. Observe the first `Production` workflow through validation, image publication and deploy. Verify the server ends on the expected SHA and public `/api/v1/ready` is healthy. If the workflow fails, inspect the failing job before changing Production manually.

---

## Self-Review Results

- **Spec coverage:** Development CI, main-only deployment, immutable GHCR images, serialized deploys, SSH host verification, server-local application secrets, pre-pull, backup, bootstrap, ordered replacement, health checks, application rollback, no automatic DB restore, dirty-checkout rejection and operator documentation are all mapped to tasks.
- **Placeholder scan:** No implementation requirement is left as `TBD`, `TODO`, or an unspecified future step.
- **Interface consistency:** `DEPLOY_BACKEND_IMAGE`, `DEPLOY_FRONTEND_IMAGE`, `IMAGE_TAG`, `deploy-production.sh <sha>`, GHCR repository names and GitHub secret names are consistent across Compose, workflow, deployment script and documentation tasks.
- **Scope:** The plan changes deployment infrastructure only; no unrelated application refactor is included.
