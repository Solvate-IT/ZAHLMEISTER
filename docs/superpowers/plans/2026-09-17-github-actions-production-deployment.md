# GitHub Actions Production Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare the complete automated Production pipeline on `development`, while ensuring GitHub Actions execute only after the user manually merges and pushes the approved state to `main`.

**Architecture:** `development` remains a passive working branch with no GitHub Action trigger. Verification there is performed through the repository's existing local/pre-deployment scripts. A single `main`-only GitHub workflow validates the exact pushed commit, publishes immutable backend/frontend GHCR images, then deploys those images over SSH using one server-side deployment script with backup, readiness checks and application-image rollback.

**Tech Stack:** GitHub Actions, Docker Engine, Docker Compose v2, GHCR, Bash, SSH, PostgreSQL 17, FastAPI/Uvicorn, nginx/Next.js static export, Traefik.

**Spec:** `docs/superpowers/specs/2026-09-17-github-actions-production-deployment-design.md`

## Global Constraints

- Work and push only on `development`; never push or merge `main` from this implementation.
- GitHub Actions must not trigger on `development`.
- The automated workflow triggers only on `push` to `main`.
- No `pull_request` or `workflow_dispatch` activation path is introduced for this production workflow.
- The user manually decides when `development` is merged/pushed to `main`.
- Do not add Kubernetes, Docker Swarm, Redis, Kafka, RabbitMQ or another reverse proxy.
- Preserve the existing layered ENV model and server-only application secrets.
- Production images use immutable full Git SHA tags; Production never depends on `latest`.
- `docker/compose.prod.yml` keeps existing `build:` definitions for local checks/emergency builds.
- Database restore is never automatic.
- Existing production security options and secret mounts remain unchanged.
- SSH host verification is mandatory; `StrictHostKeyChecking=no` is forbidden.

---

## File Structure

- Create `.github/workflows/production.yml` — the only GitHub Actions workflow needed for this feature; `main` push only.
- Modify `docker/compose.prod.yml` — transient GHCR image repository overrides while keeping local `build:` blocks.
- Create `docker/scripts/deploy-production.sh` — server-side deployment, readiness and rollback logic.
- Create `docker/scripts/deploy-production.test.sh` — deterministic deployment regression tests.
- Create `docker/scripts/ci-cd-config.test.sh` — static workflow/Compose safety checks.
- Modify `docker/predeploy.sh` — include deployment regression checks in local/project validation.
- Modify `docker/manage.sh` — include deployment regressions under existing menu option 10 only.
- Modify `docker/OPERATIONS.md` — document that normal work happens on `development` and automation begins only after the user pushes `main`.

---

### Task 1: Define main-only workflow safeguards first

**Files:**
- Create: `docker/scripts/ci-cd-config.test.sh`
- Test: `.github/workflows/production.yml`
- Test: `docker/compose.prod.yml`

**Interfaces:**
- Consumes repository files as text.
- Produces non-zero exit when the workflow can run from anything except `main` push, or when immutable image/SSH safety requirements are missing.

- [ ] **Step 1: Write the failing static test**

Create `docker/scripts/ci-cd-config.test.sh` with assertions equivalent to:

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROD="$ROOT/.github/workflows/production.yml"
COMPOSE="$ROOT/docker/compose.prod.yml"

[[ -f "$PROD" ]]

grep -q '^  push:$' "$PROD"
grep -q 'branches: \[main\]' "$PROD"
! grep -q 'development' "$PROD"
! grep -q 'pull_request:' "$PROD"
! grep -q 'workflow_dispatch:' "$PROD"
grep -q 'cancel-in-progress: false' "$PROD"
grep -q 'packages: write' "$PROD"
grep -q 'ghcr.io/solvate-it/zahlmeister-backend:${GITHUB_SHA}' "$PROD"
grep -q 'ghcr.io/solvate-it/zahlmeister-frontend:${GITHUB_SHA}' "$PROD"
grep -q 'known_hosts' "$PROD"
! grep -q 'StrictHostKeyChecking=no' "$PROD"
grep -q 'deploy-production.sh' "$PROD"

grep -Fq 'image: ${DEPLOY_BACKEND_IMAGE:-zahlmeister-backend}:${IMAGE_TAG:-latest}' "$COMPOSE"
grep -Fq 'image: ${DEPLOY_FRONTEND_IMAGE:-zahlmeister-frontend}:${IMAGE_TAG:-latest}' "$COMPOSE"

echo "CI/CD configuration checks passed."
```

- [ ] **Step 2: Verify RED**

```bash
bash docker/scripts/ci-cd-config.test.sh
```

Expected: FAIL because the workflow and Compose overrides do not yet exist.

- [ ] **Step 3: Commit/push only to `development`**

```bash
git add docker/scripts/ci-cd-config.test.sh
git commit -m "test: define main-only deployment safeguards"
git push origin development
```

---

### Task 2: Make Production Compose accept immutable registry images

**Files:**
- Modify: `docker/compose.prod.yml`
- Test: `docker/scripts/ci-cd-config.test.sh`

**Interfaces:**
- Consumes `DEPLOY_BACKEND_IMAGE`, `DEPLOY_FRONTEND_IMAGE`, `IMAGE_TAG`.
- Produces exact image refs for bootstrap/backend/worker/frontend while preserving all local build definitions.

- [ ] **Step 1: Extend tests for all four services**

```bash
[[ "$(grep -Fc 'image: ${DEPLOY_BACKEND_IMAGE:-zahlmeister-backend}:${IMAGE_TAG:-latest}' "$COMPOSE")" -eq 3 ]]
[[ "$(grep -Fc 'image: ${DEPLOY_FRONTEND_IMAGE:-zahlmeister-frontend}:${IMAGE_TAG:-latest}' "$COMPOSE")" -eq 1 ]]
grep -q '^    build:$' "$COMPOSE"
```

- [ ] **Step 2: Verify RED for Compose assertions**

```bash
bash docker/scripts/ci-cd-config.test.sh
```

- [ ] **Step 3: Replace only the four image declarations**

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

Do not add `DEPLOY_*` to tracked or private ENV files; they are transient deployment controls.

- [ ] **Step 4: Validate Compose with representative GHCR refs**

```bash
cd docker
DEPLOY_BACKEND_IMAGE=ghcr.io/solvate-it/zahlmeister-backend \
DEPLOY_FRONTEND_IMAGE=ghcr.io/solvate-it/zahlmeister-frontend \
IMAGE_TAG=0123456789abcdef0123456789abcdef01234567 \
docker compose --env-file .env.production -f compose.prod.yml config -q
cd ..
```

- [ ] **Step 5: Commit/push only to `development`**

```bash
git add docker/compose.prod.yml docker/scripts/ci-cd-config.test.sh
git commit -m "feat: allow immutable production image references"
git push origin development
```

---

### Task 3: Implement safe server-side deployment and rollback

**Files:**
- Create: `docker/scripts/deploy-production.sh`
- Create: `docker/scripts/deploy-production.test.sh`
- Reuse: `docker/scripts/backup.sh`
- Reuse: `docker/scripts/common.sh`

**Interfaces:**
- Command: `DEPLOY_BACKEND_IMAGE=<repo> DEPLOY_FRONTEND_IMAGE=<repo> IMAGE_TAG=<sha> ./docker/scripts/deploy-production.sh <sha>`
- Requires server checkout on clean `main`, exact requested SHA, `ENVIRONMENT=production`.
- Produces the requested running release or non-zero exit after safe application-image rollback where possible.

- [ ] **Step 1: Write failing deployment unit-style shell tests**

Tests must cover:

```bash
require_production_environment production
! require_production_environment development
require_sha 0123456789abcdef0123456789abcdef01234567
! require_sha latest
! require_sha abc123
```

They must also simulate the sequence:

```text
pull -> backup -> bootstrap -> worker -> backend -> backend ready -> frontend -> frontend ready -> public ready
```

Failure cases:

```text
bootstrap fails -> no service replacement
backend readiness fails -> backend/worker rollback, frontend untouched
frontend readiness fails -> frontend rollback
```

- [ ] **Step 2: Verify RED**

```bash
bash docker/scripts/deploy-production.test.sh
```

- [ ] **Step 3: Implement sourceable helpers plus guarded `main`**

Core validation:

```bash
require_production_environment() {
  [[ "$1" == production ]] || {
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
```

`main` must reject:

```text
wrong environment
non-main branch
HEAD != requested SHA
dirty checkout
missing image repository variables
```

Operational order:

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

Use existing Compose helper/configuration from `common.sh`. Pull images explicitly before backup/bootstrap. Use the existing `backup.sh`. Use bounded readiness loops and logs on timeout. Public readiness uses `curl --fail --silent --show-error --max-time 10 "${PUBLIC_APP_URL%/}/api/v1/ready"` without disabling TLS validation.

- [ ] **Step 4: Verify GREEN**

```bash
bash -n docker/scripts/deploy-production.sh docker/scripts/deploy-production.test.sh
bash docker/scripts/deploy-production.test.sh
```

- [ ] **Step 5: Commit/push only to `development`**

```bash
git add docker/scripts/deploy-production.sh docker/scripts/deploy-production.test.sh
git commit -m "feat: add safe production image deployment"
git push origin development
```

---

### Task 4: Create the single main-only GitHub workflow

**Files:**
- Create: `.github/workflows/production.yml`
- Test: `docker/scripts/ci-cd-config.test.sh`

**Interfaces:**
- Trigger: push to `main` only.
- Build input/output: `zahlmeister-backend:ci-${GITHUB_SHA}` and `zahlmeister-frontend:ci-${GITHUB_SHA}` produced by `docker/predeploy.sh`, then retagged/pushed to GHCR.
- Required GitHub secrets: `PRODUCTION_SSH_HOST`, `PRODUCTION_SSH_PORT`, `PRODUCTION_SSH_USER`, `PRODUCTION_SSH_KEY`, `PRODUCTION_SSH_KNOWN_HOSTS`.
- Production checkout: `/opt/ZAHLMEISTER`.

- [ ] **Step 1: Verify workflow tests are RED**

```bash
bash docker/scripts/ci-cd-config.test.sh
```

- [ ] **Step 2: Create `.github/workflows/production.yml` with exactly this activation model**

```yaml
name: Production

on:
  push:
    branches: [main]

permissions:
  contents: read
  packages: write

concurrency:
  group: zahlmeister-production
  cancel-in-progress: false
```

There must be no `development`, `pull_request`, or `workflow_dispatch` trigger.

- [ ] **Step 3: Add validate/publish job**

Use pinned checkout:

```yaml
- name: Check out repository
  uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
  with:
    fetch-depth: 0
```

Then:

```bash
IMAGE_TAG="ci-${GITHUB_SHA}" bash docker/predeploy.sh
printf '%s' "$GITHUB_TOKEN" | docker login ghcr.io -u "$GITHUB_ACTOR" --password-stdin
docker tag "zahlmeister-backend:ci-${GITHUB_SHA}" "ghcr.io/solvate-it/zahlmeister-backend:${GITHUB_SHA}"
docker tag "zahlmeister-frontend:ci-${GITHUB_SHA}" "ghcr.io/solvate-it/zahlmeister-frontend:${GITHUB_SHA}"
docker push "ghcr.io/solvate-it/zahlmeister-backend:${GITHUB_SHA}"
docker push "ghcr.io/solvate-it/zahlmeister-frontend:${GITHUB_SHA}"
```

- [ ] **Step 4: Add deploy job after publish**

It must `needs` the validate/publish job, create SSH key and `known_hosts`, and update remote checkout using fast-forward-only semantics:

```bash
cd /opt/ZAHLMEISTER
test -z "$(git status --porcelain)"
git fetch origin main
git checkout main
git merge --ff-only "$GITHUB_SHA"
test "$(git rev-parse HEAD)" = "$GITHUB_SHA"
```

Authenticate GHCR remotely through stdin, then run:

```bash
DEPLOY_BACKEND_IMAGE=ghcr.io/solvate-it/zahlmeister-backend \
DEPLOY_FRONTEND_IMAGE=ghcr.io/solvate-it/zahlmeister-frontend \
IMAGE_TAG="$GITHUB_SHA" \
./docker/scripts/deploy-production.sh "$GITHUB_SHA"
```

Always run remote `docker logout ghcr.io` at the end.

- [ ] **Step 5: Verify static safeguards GREEN**

```bash
bash docker/scripts/ci-cd-config.test.sh
```

Expected: PASS.

- [ ] **Step 6: Commit/push workflow only to `development`**

```bash
git add .github/workflows/production.yml docker/scripts/ci-cd-config.test.sh
git commit -m "ci: add main-only production deployment"
git push origin development
```

Important: this push must not trigger any GitHub Action because the workflow itself is scoped only to `main`.

---

### Task 5: Integrate deployment regression checks into existing local/project validation

**Files:**
- Modify: `docker/predeploy.sh`
- Modify: `docker/manage.sh`
- Modify: `docker/OPERATIONS.md`

**Interfaces:**
- `manage.sh` menu remains 1–10 + q.
- Local Development validation continues through `predeploy.sh` and menu option 10.
- GitHub remains inactive until `main` is pushed.

- [ ] **Step 1: Add new deployment files to `predeploy.sh` required/tracked file checks**

Require:

```text
.github/workflows/production.yml
docker/scripts/deploy-production.sh
docker/scripts/deploy-production.test.sh
docker/scripts/ci-cd-config.test.sh
```

Add `.github/workflows` to tracked input checks.

- [ ] **Step 2: Run deployment regressions inside existing validation stage**

After shell syntax validation:

```bash
"$SCRIPT_DIR/scripts/ci-cd-config.test.sh"
"$SCRIPT_DIR/scripts/deploy-production.test.sh"
```

- [ ] **Step 3: Extend `manage.sh` option 10 only**

```bash
run_tests() {
  compose run --rm backend pytest -q
  compose run --rm frontend sh -c 'npm ci --no-audit --no-fund && npm test && npm run typecheck'
  "$SCRIPT_DIR/scripts/platform-admin-access.test.sh"
  "$SCRIPT_DIR/scripts/ci-cd-config.test.sh"
  "$SCRIPT_DIR/scripts/deploy-production.test.sh"
}
```

Do not add a deployment menu option.

- [ ] **Step 4: Update operator documentation**

Document the normal release as:

```text
1. Development changes are pushed only to development.
2. No GitHub Action runs there.
3. Run local/project checks and review the result.
4. The user manually merges and pushes the approved state to main.
5. Only that main push starts GitHub validation, image publication and Production deployment.
6. Any failed GitHub stage prevents later deployment stages from running.
```

Document the five GitHub secrets and server prerequisites. Keep emergency manual deployment separate from normal operation.

- [ ] **Step 5: Focused verification**

```bash
bash -n docker/manage.sh docker/predeploy.sh docker/scripts/*.sh
bash docker/scripts/platform-admin-access.test.sh
bash docker/scripts/ci-cd-config.test.sh
bash docker/scripts/deploy-production.test.sh
```

- [ ] **Step 6: Commit/push only to `development`**

```bash
git add docker/predeploy.sh docker/manage.sh docker/OPERATIONS.md docker/scripts
git commit -m "docs: integrate main-only deployment safeguards"
git push origin development
```

---

### Task 6: Full Development verification and handoff

**Files:**
- Verify all files from Tasks 1–5.

**Interfaces:**
- Produces a verified `development` state ready for the user's manual promotion to `main`.

- [ ] **Step 1: Confirm branch and clean tree**

```bash
git branch --show-current
git status --short
```

Expected: `development`, clean.

- [ ] **Step 2: Run complete production-equivalent local check**

```bash
IMAGE_TAG="verify-$(git rev-parse --short HEAD)" bash docker/predeploy.sh
```

Expected: all existing production-equivalent checks and the new deployment regressions pass.

- [ ] **Step 3: Verify generated runtime images exist**

```bash
TAG="verify-$(git rev-parse --short HEAD)"
docker image inspect "zahlmeister-backend:${TAG}" >/dev/null
docker image inspect "zahlmeister-frontend:${TAG}" >/dev/null
```

- [ ] **Step 4: Reconfirm workflow has main-only activation**

```bash
grep -n 'push:' .github/workflows/production.yml
grep -n 'branches:' .github/workflows/production.yml
! grep -q 'development' .github/workflows/production.yml
! grep -q 'pull_request:' .github/workflows/production.yml
! grep -q 'workflow_dispatch:' .github/workflows/production.yml
```

- [ ] **Step 5: Push final verified state to `development` only**

```bash
git push origin development
```

Do not merge or push `main`.

- [ ] **Step 6: Prepare repository secrets before first user-driven main release**

The user/GitHub repository must have:

```text
PRODUCTION_SSH_HOST
PRODUCTION_SSH_PORT
PRODUCTION_SSH_USER
PRODUCTION_SSH_KEY
PRODUCTION_SSH_KNOWN_HOSTS
```

The known-hosts entry must be verified out-of-band.

- [ ] **Step 7: First activation happens only after the user pushes `main`**

Once the user manually merges the verified `development` state and pushes `main`, the production workflow runs automatically. Until that moment, no GitHub Action should execute because of these changes.

---

## Self-Review Results

- **Spec coverage:** main-only activation, local Development verification, immutable GHCR images, serialized deploy, SSH host verification, backup, bootstrap, ordered replacement, readiness checks, rollback and operator documentation are covered.
- **Trigger correctness:** no task creates a Development, PR or manual workflow trigger.
- **Branch safety:** every implementation commit/push explicitly targets `development`; promotion to `main` is left to the user.
- **Scope:** no unrelated application changes or new infrastructure are introduced.
