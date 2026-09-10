#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DOCKER_DIR="$SCRIPT_DIR"
source "$SCRIPT_DIR/scripts/env.sh"

PROD_FILE="$SCRIPT_DIR/compose.prod.yml"
IMAGE_TAG="${IMAGE_TAG:-predeploy}"
BACKEND_TEST_IMAGE="zahlmeister-backend-test:${IMAGE_TAG}"
FRONTEND_TEST_IMAGE="zahlmeister-frontend-test:${IMAGE_TAG}"
BACKEND_RUNTIME_IMAGE="zahlmeister-backend:${IMAGE_TAG}"
FRONTEND_RUNTIME_IMAGE="zahlmeister-frontend:${IMAGE_TAG}"
SAFE_TAG="$(printf '%s' "$IMAGE_TAG" | tr -c 'A-Za-z0-9_.-' '-')"
RUN_ID="${SAFE_TAG}-$$"
NETWORK="zahlmeister-predeploy-${RUN_ID}"
DB_CONTAINER="zahlmeister-predeploy-db-${RUN_ID}"
WORKER_CONTAINER="zahlmeister-predeploy-worker-${RUN_ID}"
BACKEND_CONTAINER="zahlmeister-predeploy-backend-${RUN_ID}"
FRONTEND_CONTAINER="zahlmeister-predeploy-frontend-${RUN_ID}"
TEST_DB_NAME="zahlmeister_predeploy"
TEST_DB_USER="predeploy"
TEST_DB_PASSWORD="predeploy-only-password"
TEST_DATABASE_URL="postgresql+asyncpg://${TEST_DB_USER}:${TEST_DB_PASSWORD}@db:5432/${TEST_DB_NAME}"

cleanup() {
  docker rm -f "$FRONTEND_CONTAINER" "$BACKEND_CONTAINER" "$WORKER_CONTAINER" "$DB_CONTAINER" >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

cd "$PROJECT_DIR"

echo "== Zahlmeister pre-deployment checks =="
echo "Environment: $ENVIRONMENT"

required_files=(
  "backend/pyproject.toml"
  "backend/app/main.py"
  "backend/app/worker.py"
  "backend/app/core/config.py"
  "backend/app/db/bootstrap.py"
  "backend/app/api/routes/health.py"
  "backend/tests/test_channel_strategy.py"
  "backend/tests/test_integrations.py"
  "frontend/package.json"
  "frontend/package-lock.json"
  "frontend/next.config.ts"
  "frontend/tsconfig.json"
  "frontend/src/lib/i18n.tsx"
  "frontend/src/lib/native.ts"
  "frontend/public/manifest.webmanifest"
  "mobile/package.json"
  "mobile/package-lock.json"
  "mobile/capacitor.config.ts"
  "mobile/tool/bootstrap_mobile.sh"
  "docker/.env.development"
  "docker/.env.production"
  "docker/compose.yml"
  "docker/compose.prod.yml"
  "docker/backend.Dockerfile"
  "docker/frontend.Dockerfile"
  "docker/nginx.conf"
  "docker/manage.sh"
  "docker/predeploy.sh"
  "docker/scripts/env.sh"
)

echo
echo "[1/11] Checking required files..."
for file in "${required_files[@]}"; do
  [[ -f "$file" ]] || { echo "Missing required file: $file"; exit 1; }
done

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo
echo "[2/11] Checking Git tracking and packaging inputs..."
  for file in "${required_files[@]}"; do
    git ls-files --error-unmatch "$file" >/dev/null 2>&1 || {
      echo "Required runtime file is not tracked by Git: $file"
      git check-ignore -v "$file" || true
      exit 1
    }
  done

  runtime_paths=(
    backend/app backend/locales backend/pyproject.toml
    frontend/src frontend/public frontend/package.json frontend/package-lock.json frontend/next.config.ts frontend/tsconfig.json
    mobile/assets mobile/mobile-links mobile/tool mobile/package.json mobile/package-lock.json mobile/capacitor.config.ts
    docker/.env.development docker/.env.production docker/backend.Dockerfile docker/frontend.Dockerfile
    docker/compose.yml docker/compose.prod.yml docker/nginx.conf docker/manage.sh docker/predeploy.sh docker/scripts
  )
  untracked="$(git status --porcelain --untracked-files=all -- "${runtime_paths[@]}" | awk 'substr($0,1,2)=="??" {print substr($0,4)}')"
  if [[ -n "$untracked" ]]; then
    echo "Untracked files would affect a local runtime/build but are absent from GitHub:" >&2
    printf '%s\n' "$untracked" >&2
    exit 1
  fi
else
  echo
echo "[2/11] Git tracking check skipped (not inside a Git work tree)."
fi

echo
echo "[3/11] Validating environment parity, Compose and scripts..."
check_env_parity
docker compose "${COMPOSE_ENV_ARGS[@]}" -f "$PROD_FILE" config -q
docker compose "${COMPOSE_ENV_ARGS[@]}" -f "$SCRIPT_DIR/compose.yml" config -q
bash -n "$SCRIPT_DIR/manage.sh" "$SCRIPT_DIR/predeploy.sh" "$SCRIPT_DIR"/scripts/*.sh "$PROJECT_DIR/mobile/tool/bootstrap_mobile.sh"
if grep -q 'Mail.ReadWrite' "$SCRIPT_DIR/compose.prod.yml" "$SCRIPT_DIR/.env.development" "$SCRIPT_DIR/.env.production"; then
  echo "Microsoft 365 configuration still requests Mail.ReadWrite." >&2
  exit 1
fi
grep -q '^OAUTH_CALLBACK_BASE_URL=' "$SCRIPT_DIR/.env.production"
grep -q '^PONTO_CONNECT_ENVIRONMENT=live$' "$SCRIPT_DIR/.env.production"

echo
echo "[4/11] Building backend test image and running backend tests..."
docker build --target test -f "$SCRIPT_DIR/backend.Dockerfile" -t "$BACKEND_TEST_IMAGE" .
docker run --rm \
  -e ENVIRONMENT=test \
  -e READINESS_REQUIRE_WORKER=false \
  "$BACKEND_TEST_IMAGE" \
  sh -c 'ruff check app tests && pytest -q'

echo
echo "[5/11] Testing fresh schema bootstrap against PostgreSQL 17..."
docker network create "$NETWORK" >/dev/null
docker run -d --name "$DB_CONTAINER" --network "$NETWORK" --network-alias db \
  -e POSTGRES_DB="$TEST_DB_NAME" \
  -e POSTGRES_USER="$TEST_DB_USER" \
  -e POSTGRES_PASSWORD="$TEST_DB_PASSWORD" \
  postgres:17-alpine >/dev/null
DB_READY=0
for _ in $(seq 1 30); do
  if docker exec "$DB_CONTAINER" pg_isready -U "$TEST_DB_USER" -d "$TEST_DB_NAME" >/dev/null 2>&1; then
    DB_READY=1
    break
  fi
  sleep 1
done
[[ "$DB_READY" == "1" ]] || { docker logs "$DB_CONTAINER"; echo "PostgreSQL predeploy database did not become ready." >&2; exit 1; }

docker run --rm --network "$NETWORK" \
  -e ENVIRONMENT=test \
  -e DATABASE_URL="$TEST_DATABASE_URL" \
  "$BACKEND_TEST_IMAGE" \
  sh -c 'python -m app.db.bootstrap && python -m app.db.bootstrap'

echo
echo "[6/11] Building frontend test stage..."
docker build --target test -f "$SCRIPT_DIR/frontend.Dockerfile" -t "$FRONTEND_TEST_IMAGE" .

echo
echo "[7/11] Building the actual production images..."
IMAGE_TAG="$IMAGE_TAG" docker compose "${COMPOSE_ENV_ARGS[@]}" -f "$PROD_FILE" build backend frontend

APP_RUNTIME_UID_VALUE="$(env_value APP_RUNTIME_UID 10001)"
APP_RUNTIME_GID_VALUE="$(env_value APP_RUNTIME_GID 10001)"

echo
echo "[8/11] Checking final runtime images..."
docker run --rm \
  -e EXPECTED_RUNTIME_UID="$APP_RUNTIME_UID_VALUE" \
  "$BACKEND_RUNTIME_IMAGE" \
  sh -c '
    command -v tesseract >/dev/null &&
    command -v pdftoppm >/dev/null &&
    command -v qrencode >/dev/null &&
    python -m pip check &&
    python -c "import reportlab" &&
    tesseract --list-langs 2>/dev/null | grep -qx Latin &&
    tesseract --list-langs 2>/dev/null | grep -qx ell &&
    tesseract --list-langs 2>/dev/null | grep -qx bul &&
    test "$(id -u)" = "$EXPECTED_RUNTIME_UID" &&
    test ! -d /app/tests &&
    ! command -v pytest >/dev/null &&
    ! command -v ruff >/dev/null
  '

docker run --rm --add-host backend:127.0.0.1 --entrypoint sh "$FRONTEND_RUNTIME_IMAGE" -c '
    nginx -t &&
    test -f /usr/share/nginx/html/index.html &&
    test -f /usr/share/nginx/html/app/index.html &&
    test -f /usr/share/nginx/html/payment/index.html &&
    test -f /usr/share/nginx/html/action/index.html &&
    test -f /usr/share/nginx/html/robots.txt &&
    test -f /usr/share/nginx/html/sitemap.xml &&
    test -f /usr/share/nginx/html/manifest.webmanifest &&
    test -f /usr/share/nginx/html/favicon.png &&
    test -f /usr/share/nginx/html/icons/Icon-512.png &&
    test -f /usr/share/nginx/html/brand/logo.png &&
    test -d /usr/share/nginx/html/_next/static
  '

docker run --rm --network "$NETWORK" \
  -e ENVIRONMENT=test \
  -e DATABASE_URL="$TEST_DATABASE_URL" \
  "$BACKEND_RUNTIME_IMAGE" \
  python -m app.db.bootstrap

echo
echo "[9/11] Starting production runtime smoke test..."
runtime_env=(
  -e ENVIRONMENT=production
  -e DATABASE_URL="$TEST_DATABASE_URL"
  -e APP_SECRET=0123456789abcdef0123456789abcdef
  -e CORS_ORIGINS=https://app.example.test,capacitor://localhost,https://localhost
  -e PUBLIC_APP_URL=https://app.example.test
  -e OAUTH_CALLBACK_BASE_URL=https://app.example.test
  -e READINESS_REQUIRE_WORKER=true
  -e WORKER_HEARTBEAT_SECONDS=2
  -e WORKER_STALE_SECONDS=20
  -e MAIL_DELIVERY_MODE=smtp
  -e MAIL_FROM_ADDRESS=noreply@example.test
  -e MAIL_FROM_NAME=Zahlmeister
  -e MAIL_REPLY_DOMAIN=reply.example.test
  -e CONTACT_RECIPIENT=support@example.test
  -e SMTP_HOST=smtp.example.test
  -e SMTP_PORT=587
  -e SMTP_STARTTLS=true
  -e PLATFORM_IMAP_HOST=imap.example.test
  -e PLATFORM_IMAP_PORT=993
  -e PLATFORM_IMAP_USERNAME=reply@example.test
  -e PLATFORM_IMAP_PASSWORD=predeploy-only-password
  -e PLATFORM_IMAP_SSL=true
  -e PONTO_CONNECT_ENVIRONMENT=live
)
runtime_security=(
  --read-only
  --tmpfs /tmp:size=128m,mode=1777
  --security-opt no-new-privileges:true
  --cap-drop ALL
  --user "$APP_RUNTIME_UID_VALUE:$APP_RUNTIME_GID_VALUE"
  --network "$NETWORK"
)

docker run -d --name "$WORKER_CONTAINER" "${runtime_security[@]}" "${runtime_env[@]}" \
  "$BACKEND_RUNTIME_IMAGE" python -m app.worker >/dev/null
docker run -d --name "$BACKEND_CONTAINER" --network-alias backend "${runtime_security[@]}" "${runtime_env[@]}" \
  "$BACKEND_RUNTIME_IMAGE" uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 --no-access-log >/dev/null

RUNTIME_READY=0
for _ in $(seq 1 40); do
  if ! docker inspect -f '{{.State.Running}}' "$WORKER_CONTAINER" 2>/dev/null | grep -qx true; then
    docker logs "$WORKER_CONTAINER" || true
    echo "Production worker exited during smoke test." >&2
    exit 1
  fi
  if ! docker inspect -f '{{.State.Running}}' "$BACKEND_CONTAINER" 2>/dev/null | grep -qx true; then
    docker logs "$BACKEND_CONTAINER" || true
    echo "Production backend exited during smoke test." >&2
    exit 1
  fi
  if docker exec "$BACKEND_CONTAINER" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/ready', timeout=2)" >/dev/null 2>&1; then
    RUNTIME_READY=1
    break
  fi
  sleep 1
done
if [[ "$RUNTIME_READY" != "1" ]]; then
  docker logs "$WORKER_CONTAINER" || true
  docker logs "$BACKEND_CONTAINER" || true
  echo "Production /ready endpoint did not become healthy." >&2
  exit 1
fi

docker exec "$BACKEND_CONTAINER" python -c "import urllib.error,urllib.request; u='http://127.0.0.1:8000/api/docs';
try: urllib.request.urlopen(u,timeout=2); raise SystemExit('production docs must be disabled')
except urllib.error.HTTPError as exc: assert exc.code == 404"

docker run -d --name "$FRONTEND_CONTAINER" --network "$NETWORK" "$FRONTEND_RUNTIME_IMAGE" >/dev/null
FRONTEND_READY=0
for _ in $(seq 1 20); do
  if ! docker inspect -f '{{.State.Running}}' "$FRONTEND_CONTAINER" 2>/dev/null | grep -qx true; then
    docker logs "$FRONTEND_CONTAINER" || true
    echo "Production frontend exited during smoke test." >&2
    exit 1
  fi
  if docker exec "$FRONTEND_CONTAINER" wget -qO- http://127.0.0.1/ >/dev/null 2>&1 && \
     docker exec "$FRONTEND_CONTAINER" wget -qO- http://127.0.0.1/api/v1/ready | grep -q 'ready'; then
    FRONTEND_READY=1
    break
  fi
  sleep 1
done
if [[ "$FRONTEND_READY" != "1" ]]; then
  docker logs "$FRONTEND_CONTAINER" || true
  echo "Production frontend/API proxy did not become healthy." >&2
  exit 1
fi

echo
echo "[10/11] Checking Capacitor source and legacy runtime references..."
grep -q 'appId: "at.solvate.zahlmeister"' mobile/capacitor.config.ts
grep -q 'webDir: "../frontend/out"' mobile/capacitor.config.ts
! grep -R --exclude-dir=node_modules -niE '(^|[^[:alnum:]_])(flutter|dart)([^[:alnum:]_]|$)' frontend mobile docker/frontend.Dockerfile docker/frontend.Dockerfile.dev docker/compose.yml 2>/dev/null || {
  echo "Flutter/Dart references remain in the new frontend/mobile runtime paths." >&2
  exit 1
}

echo
echo "[11/11] Checking secrets, keys and backup exclusions..."
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if git ls-files 'docker/secrets/production/*' 'docker/backups/*' | grep -vE '/\.gitkeep$' | grep -q .; then
    echo "Production secrets or backups must not be tracked by Git." >&2
    exit 1
  fi
  if git ls-files | grep -E '\.(pem|key|p12|pfx|crt|cer)$' | grep -q .; then
    echo "Certificate/private-key material must not be tracked by Git." >&2
    exit 1
  fi
  if git grep -nE 'BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY' -- . >/dev/null 2>&1; then
    echo "A private key marker exists in tracked repository content." >&2
    exit 1
  fi
fi

echo
echo "Pre-deployment checks passed."
