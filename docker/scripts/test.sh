#!/usr/bin/env bash
# The production gate. GitHub Actions runs `./docker/scripts/test.sh all` on
# every push to main and deploys only when it passes; manage.sh -> 7) runs the
# same command locally.
#
#   all        pre-deployment checks, then the Trivy security scans (default)
#   predeploy  pre-deployment checks only
#
# Images are tagged with IMAGE_TAG (default ci-runtime); the workflow pushes
# zahlmeister-backend:ci-runtime and zahlmeister-frontend:ci-runtime after a
# successful run.
set -euo pipefail

DOCKER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="$(cd "$DOCKER_DIR/.." && pwd)"
source "$DOCKER_DIR/scripts/env.sh"

case "${1:-all}" in
  all|security) RUN_SECURITY=1; STAGES=12 ;;
  predeploy) RUN_SECURITY=0; STAGES=11 ;;
  *)
    echo "Usage: $0 [all|predeploy]" >&2
    exit 2
    ;;
esac

PROD_FILE="$DOCKER_DIR/compose.prod.yml"
DOCKERFILE="$DOCKER_DIR/Dockerfile"
IMAGE_TAG="${IMAGE_TAG:-ci-runtime}"
BACKEND_TEST_IMAGE="zahlmeister-backend-test:${IMAGE_TAG}"
FRONTEND_TEST_IMAGE="zahlmeister-frontend-test:${IMAGE_TAG}"
BACKEND_RUNTIME_IMAGE="zahlmeister-backend:${IMAGE_TAG}"
FRONTEND_RUNTIME_IMAGE="zahlmeister-frontend:${IMAGE_TAG}"
# Container, network and Compose project names: lowercase, PID last (manage.sh
# -> 5) keeps everything of a run whose PID is still a running test.sh).
SAFE_TAG="$(printf '%s' "$IMAGE_TAG" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9_-' '-')"
RUN_ID="${SAFE_TAG}-$$"
NETWORK="zahlmeister-predeploy-${RUN_ID}"
DB_CONTAINER="zahlmeister-predeploy-db-${RUN_ID}"
SMOKE_PROJECT="zahlmeister-predeploy-${RUN_ID}"
SMOKE_PROXY_NETWORK="zahlmeister-predeploy-proxy-${RUN_ID}"
SMOKE_DIR=""
TEST_DB_NAME="zahlmeister_predeploy"
TEST_DB_USER="predeploy"
TEST_DB_PASSWORD="predeploy-only-password"
TEST_DATABASE_URL="postgresql+asyncpg://${TEST_DB_USER}:${TEST_DB_PASSWORD}@db:5432/${TEST_DB_NAME}"
ENV_PARSER_TEST_FILE="/tmp/zahlmeister-env-parser-test-${RUN_ID}"
STAGE=0

stage() {
  STAGE=$((STAGE + 1))
  echo
  echo "[$STAGE/$STAGES] $*"
}

# compose.prod.yml with nothing but the given env file and secrets directory.
# env.sh exported this gate's own (development) values, and exported values
# would win over --env-file.
prod_compose() {
  local env_file="$1" secrets_dir="$2"
  shift 2
  (
    while IFS= read -r key; do unset "$key"; done < <(extract_env_keys "$env_file")
    unset COMPOSE_FILE COMPOSE_PROJECT_NAME COMPOSE_PROFILES
    export INTERNAL_SECRETS_DIR="$secrets_dir"
    docker compose --env-file "$env_file" -f "$PROD_FILE" "$@"
  )
}

smoke_compose() {
  prod_compose "$SMOKE_DIR/smoke.env" "$SMOKE_DIR/secrets" -p "$SMOKE_PROJECT" "$@"
}

smoke_fail() {
  smoke_compose ps -a || true
  smoke_compose logs --tail=100 || true
  echo "$*" >&2
  exit 1
}

cleanup() {
  if [[ -n "$SMOKE_DIR" ]]; then
    smoke_compose down -v --remove-orphans >/dev/null 2>&1 || true
    rm -rf "$SMOKE_DIR"
  fi
  docker network rm "$SMOKE_PROXY_NETWORK" >/dev/null 2>&1 || true
  docker rm -f "$DB_CONTAINER" >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
  rm -f "$ENV_PARSER_TEST_FILE"
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
  "frontend/tests/i18n-ui.test.mjs"
  "frontend/public/manifest.webmanifest"
  "mobile/package.json"
  "mobile/package-lock.json"
  "mobile/capacitor.config.ts"
  "mobile/tool/bootstrap_mobile.sh"
  "mobile/tool/build_android.sh"
  "mobile/tool/android_device.sh"
  "mobile/android/app/build.gradle"
  "docker/.env.development"
  "docker/.env.production"
  "docker/compose.yml"
  "docker/compose.prod.yml"
  "docker/Dockerfile"
  ".dockerignore"
  "docker/nginx.conf"
  "docker/manage.sh"
  "docker/scripts/env.sh"
  "docker/scripts/db.sh"
  "docker/scripts/reload-production-env.sh"
  "docker/scripts/deploy-production.sh"
  "docker/scripts/test.sh"
  ".github/workflows/production.yml"
)

stage "Checking required files..."
for file in "${required_files[@]}"; do
  [[ -f "$file" ]] || { echo "Missing required file: $file"; exit 1; }
done

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  stage "Checking Git tracking and packaging inputs..."
  for file in "${required_files[@]}"; do
    git ls-files --error-unmatch "$file" >/dev/null 2>&1 || {
      echo "Required runtime file is not tracked by Git: $file"
      git check-ignore -v "$file" || true
      exit 1
    }
  done

  runtime_paths=(
    backend/app backend/locales backend/pyproject.toml
    frontend/src frontend/public frontend/tests frontend/package.json frontend/package-lock.json frontend/next.config.ts frontend/tsconfig.json
    mobile/assets mobile/mobile-links mobile/tool mobile/package.json mobile/package-lock.json mobile/capacitor.config.ts mobile/android
    docker/.env.development docker/.env.production docker/Dockerfile .dockerignore
    docker/compose.yml docker/compose.prod.yml docker/nginx.conf docker/manage.sh docker/scripts
  )
  untracked="$(git status --porcelain --untracked-files=all -- "${runtime_paths[@]}" | awk 'substr($0,1,2)=="??" {print substr($0,4)}')"
  if [[ -n "$untracked" ]]; then
    echo "Untracked files would affect a local runtime/build but are absent from GitHub:" >&2
    printf '%s\n' "$untracked" >&2
    exit 1
  fi
else
  stage "Git tracking check skipped (not inside a Git work tree)."
fi

stage "Validating environment parity, Compose and scripts..."
check_env_parity
docker compose "${COMPOSE_ENV_ARGS[@]}" -f "$PROD_FILE" config -q
docker compose "${COMPOSE_ENV_ARGS[@]}" -f "$DOCKER_DIR/compose.yml" config -q
bash -n "$DOCKER_DIR/manage.sh" "$DOCKER_DIR"/scripts/*.sh "$PROJECT_DIR/mobile/tool/bootstrap_mobile.sh" "$PROJECT_DIR/mobile/tool/build_android.sh" "$PROJECT_DIR/mobile/tool/android_device.sh"
grep -q '^    absolute_redirect off;$' "$DOCKER_DIR/nginx.conf"
grep -q '^    port_in_redirect off;$' "$DOCKER_DIR/nginx.conf"
# Blanks after the values are deliberate: the parser must trim them.
printf '%s\n' "TEST_SINGLE='alpha\$beta'   " 'TEST_DOUBLE="gamma$delta"   ' 'TEST_PLAIN=plain   ' > "$ENV_PARSER_TEST_FILE"
[[ "$(read_env_value_from_file "$ENV_PARSER_TEST_FILE" TEST_SINGLE)" == 'alpha$beta' ]] || { echo "Single-quoted env parsing failed." >&2; exit 1; }
[[ "$(read_env_value_from_file "$ENV_PARSER_TEST_FILE" TEST_DOUBLE)" == 'gamma$delta' ]] || { echo "Double-quoted env parsing failed." >&2; exit 1; }
[[ "$(read_env_value_from_file "$ENV_PARSER_TEST_FILE" TEST_PLAIN)" == "plain" ]] || { echo "Unquoted env parsing failed." >&2; exit 1; }
rm -f "$ENV_PARSER_TEST_FILE"
if grep -q 'Mail.ReadWrite' "$PROD_FILE" "$PROJECT_DIR/backend/app/core/config.py" "$DOCKER_DIR/.env.development" "$DOCKER_DIR/.env.production"; then
  echo "Microsoft 365 configuration still requests Mail.ReadWrite." >&2
  exit 1
fi
grep -q '^OAUTH_CALLBACK_BASE_URL=' "$DOCKER_DIR/.env.production"
grep -q '^PONTO_CONNECT_ENVIRONMENT=live$' "$DOCKER_DIR/.env.production"
# Production keeps its data only while the Compose project and the database
# volume keep their names; a rename would start it on a new, empty volume.
prod_config="$(prod_compose "$PROD_ENV_FILE" "$DOCKER_DIR/secrets/production" config)"
[[ "$(head -n 1 <<<"$prod_config")" == "name: zahlmeister" ]] \
  && grep -x -A1 '  postgres18_data:' <<<"$prod_config" | grep -qx '    name: zahlmeister_postgres18_data' \
  && grep -x -A1 '        source: postgres18_data' <<<"$prod_config" | grep -qx '        target: /var/lib/postgresql' || {
  echo "Production must keep Compose project 'zahlmeister' and database volume 'postgres18_data'" >&2
  echo "mounted at /var/lib/postgresql; otherwise it starts on an empty database." >&2
  exit 1
}

stage "Building backend test image and running backend tests..."
docker build --target backend-test -f "$DOCKERFILE" -t "$BACKEND_TEST_IMAGE" .
docker run --rm \
  -e ENVIRONMENT=test \
  -e READINESS_REQUIRE_WORKER=false \
  "$BACKEND_TEST_IMAGE" \
  python -m pytest -q

stage "Testing fresh schema bootstrap against PostgreSQL 18..."
docker network create "$NETWORK" >/dev/null
docker run -d --name "$DB_CONTAINER" --network "$NETWORK" --network-alias db \
  -e POSTGRES_DB="$TEST_DB_NAME" \
  -e POSTGRES_USER="$TEST_DB_USER" \
  -e POSTGRES_PASSWORD="$TEST_DB_PASSWORD" \
  postgres:18.6-alpine >/dev/null
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

stage "Building frontend test stage..."
docker build --target frontend-test -f "$DOCKERFILE" -t "$FRONTEND_TEST_IMAGE" .

stage "Building the actual production images..."
docker build --target backend -f "$DOCKERFILE" -t "$BACKEND_RUNTIME_IMAGE" .
docker build --target frontend -f "$DOCKERFILE" -t "$FRONTEND_RUNTIME_IMAGE" .

APP_RUNTIME_UID_VALUE="$(env_value APP_RUNTIME_UID 10001)"

stage "Checking final runtime images..."
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

docker run --rm --read-only --tmpfs /tmp:size=64m,mode=1777 --security-opt no-new-privileges:true --cap-drop ALL \
  --add-host zahlmeister-api-internal:127.0.0.1 --entrypoint sh "$FRONTEND_RUNTIME_IMAGE" -c '
    test "$(id -u)" != "0" &&
    nginx -t &&
    nginx -T 2>&1 | grep -q "client_body_temp_path /tmp/client_body;" &&
    nginx -T 2>&1 | grep -q "proxy_temp_path /tmp/proxy;" &&
    nginx -T 2>&1 | grep -q "fastcgi_temp_path /tmp/fastcgi;" &&
    nginx -T 2>&1 | grep -q "uwsgi_temp_path /tmp/uwsgi;" &&
    nginx -T 2>&1 | grep -q "scgi_temp_path /tmp/scgi;" &&
    test -f /usr/share/nginx/html/index.html &&
    test -f /usr/share/nginx/html/app/index.html &&
    test -f /usr/share/nginx/html/admin/index.html &&
    test -f /usr/share/nginx/html/payment/index.html &&
    test -f /usr/share/nginx/html/action/index.html &&
    test -f /usr/share/nginx/html/robots.txt &&
    test -f /usr/share/nginx/html/sitemap.xml &&
    test -f /usr/share/nginx/html/manifest.webmanifest &&
    test -f /usr/share/nginx/html/favicon.svg &&
    test -f /usr/share/nginx/html/icons/app-512-v4.png &&
    test -f /usr/share/nginx/html/brand/logo.png &&
    test -d /usr/share/nginx/html/_next/static
  '

docker run --rm --network "$NETWORK" \
  -e ENVIRONMENT=test \
  -e DATABASE_URL="$TEST_DATABASE_URL" \
  "$BACKEND_RUNTIME_IMAGE" \
  python -m app.db.bootstrap

# The real compose.prod.yml, started in the order deploy-production.sh uses,
# with the images just built, throwaway secrets and example.test endpoints.
stage "Starting the production stack from compose.prod.yml..."
SMOKE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/zahlmeister-predeploy-${RUN_ID}.XXXXXX")"
mkdir "$SMOKE_DIR/secrets"
chmod 755 "$SMOKE_DIR" "$SMOKE_DIR/secrets"
printf '%s\n' "$TEST_DB_PASSWORD" > "$SMOKE_DIR/secrets/postgres_password"
printf '%s\n' "postgresql+asyncpg://zahlmeister:${TEST_DB_PASSWORD}@db:5432/zahlmeister" > "$SMOKE_DIR/secrets/database_url"
printf '%s\n' 0123456789abcdef0123456789abcdef > "$SMOKE_DIR/secrets/app_secret"
printf '%s\n' predeploy-only-admin-password > "$SMOKE_DIR/secrets/platform_admin_password"
printf '%s\n' predeploy-only-monitoring-token > "$SMOKE_DIR/secrets/monitoring_token"
chmod 644 "$SMOKE_DIR"/secrets/*

smoke_overrides=(
  "COMPOSE_PROJECT_NAME=$SMOKE_PROJECT"
  "PROXY_NETWORK=$SMOKE_PROXY_NETWORK"
  "BACKEND_IMAGE=$BACKEND_RUNTIME_IMAGE"
  "FRONTEND_IMAGE=$FRONTEND_RUNTIME_IMAGE"
  "APP_HOST=app.example.test"
  "PUBLIC_APP_URL=https://app.example.test"
  "OAUTH_CALLBACK_BASE_URL=https://app.example.test"
  "CORS_ORIGINS=https://app.example.test,capacitor://localhost,https://localhost"
  "PLATFORM_ADMIN_EMAILS=admin@example.test"
  "PLATFORM_ADMIN_BOOTSTRAP_EMAIL=admin@example.test"
  "MAIL_FROM_ADDRESS=noreply@example.test"
  "MAIL_REPLY_DOMAIN=reply.example.test"
  "CONTACT_RECIPIENT=support@example.test"
  "SMTP_HOST=smtp.example.test"
  "SMTP_PORT=587"
  "SMTP_STARTTLS=true"
  "PLATFORM_IMAP_HOST=imap.example.test"
  "PLATFORM_IMAP_PORT=993"
  "PLATFORM_IMAP_USERNAME=reply@example.test"
  "PLATFORM_IMAP_PASSWORD=predeploy-only-password"
  "PLATFORM_IMAP_SSL=true"
)
override_keys="$(printf '%s\n' "${smoke_overrides[@]%%=*}" | paste -sd '|')"
{
  grep -vE "^[[:space:]]*(${override_keys})[[:space:]]*=" "$PROD_ENV_FILE"
  printf '%s\n' "${smoke_overrides[@]}"
} > "$SMOKE_DIR/smoke.env"

docker network create "$SMOKE_PROXY_NETWORK" >/dev/null
smoke_compose config -q
smoke_compose up -d --wait --wait-timeout 90 db || smoke_fail "PostgreSQL did not become healthy."
smoke_compose run --rm -T --no-deps bootstrap </dev/null || smoke_fail "Production bootstrap failed."
smoke_compose up -d --no-deps --wait --wait-timeout 180 worker backend || smoke_fail "Production backend /ready did not become healthy."
smoke_compose up -d --no-deps --wait --wait-timeout 120 frontend || smoke_fail "Production frontend/API proxy did not become healthy."

for service in backend worker frontend; do
  cid="$(smoke_compose ps -q "$service")"
  expected="$BACKEND_RUNTIME_IMAGE"
  [[ "$service" != "frontend" ]] || expected="$FRONTEND_RUNTIME_IMAGE"
  [[ "$(docker inspect --format '{{.Config.Image}}' "$cid")" == "$expected" ]] || smoke_fail "$service does not run $expected."
  [[ "$(docker inspect --format '{{.HostConfig.ReadonlyRootfs}} {{.HostConfig.CapDrop}} {{.HostConfig.SecurityOpt}}' "$cid")" == "true [ALL] [no-new-privileges:true]" ]] \
    || smoke_fail "$service does not run read-only, without capabilities and with no-new-privileges."
done

smoke_compose exec -T backend python -c "import urllib.error,urllib.request; u='http://127.0.0.1:8000/api/docs';
try: urllib.request.urlopen(u,timeout=2); raise SystemExit('production docs must be disabled')
except urllib.error.HTTPError as exc: assert exc.code == 404" || smoke_fail "Production API docs are not disabled."

smoke_compose exec -T frontend sh -c '
  wget -qO /tmp/root.html http://127.0.0.1:8080/ &&
  wget -qO /tmp/admin.html http://127.0.0.1:8080/admin/ &&
  ! cmp -s /tmp/root.html /tmp/admin.html &&
  wget -qO- http://127.0.0.1:8080/api/v1/ready | grep -q ready
' || smoke_fail "Production frontend routing or API proxy failed."

smoke_compose down -v --remove-orphans >/dev/null

stage "Checking Capacitor source and legacy runtime references..."
grep -q 'appId: "at.solvate.zahlmeister"' mobile/capacitor.config.ts
grep -q 'webDir: "../frontend/out"' mobile/capacitor.config.ts
grep -q 'applicationId "at.solvate.zahlmeister"' mobile/android/app/build.gradle
# Local Gradle/Next output and built APK/AAB files are binary and not source.
! grep -R --exclude-dir=node_modules --exclude-dir=dist --exclude-dir=build --exclude-dir=.gradle -niE '(^|[^[:alnum:]_])(flutter|dart)([^[:alnum:]_]|$)' frontend mobile docker/Dockerfile docker/compose.yml 2>/dev/null || {
  echo "Flutter/Dart references remain in the new frontend/mobile runtime paths." >&2
  exit 1
}

stage "Checking secrets, keys and backup exclusions..."
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if git ls-files 'docker/secrets/production/*' 'docker/secrets/android/*' 'docker/backups/*' | grep -vE '/\.gitkeep$' | grep -q .; then
    echo "Production secrets or backups must not be tracked by Git." >&2
    exit 1
  fi
  if git ls-files | grep -E '\.(pem|key|p12|pfx|crt|cer|jks|keystore)$' | grep -q .; then
    echo "Certificate/private-key material must not be tracked by Git." >&2
    exit 1
  fi
  if git grep -nE 'BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY' -- . >/dev/null 2>&1; then
    echo "A private key marker exists in tracked repository content." >&2
    exit 1
  fi
fi

if (( RUN_SECURITY )); then
  stage "Running the Trivy security scans..."
  TRIVY_IMAGE="${TRIVY_IMAGE:-aquasec/trivy:0.74.0}"
  TRIVY_CACHE="${TRIVY_CACHE_DIR:-$DOCKER_DIR/.trivy-cache}"
  mkdir -p "$TRIVY_CACHE"

  run_trivy() {
    docker run --rm \
      -v /var/run/docker.sock:/var/run/docker.sock:ro \
      -v "$TRIVY_CACHE:/root/.cache/" \
      -v "$PROJECT_DIR:/workspace:ro" \
      "$TRIVY_IMAGE" "$@"
  }

  echo "== Security: repository secret scan =="
  run_trivy fs \
    --scanners secret \
    --skip-files /workspace/docker/.env \
    --skip-dirs /workspace/docker/secrets \
    --skip-dirs /workspace/docker/backups \
    --exit-code 1 \
    /workspace

  echo "== Security: repository dependency vulnerabilities =="
  run_trivy fs --scanners vuln --ignore-unfixed --severity CRITICAL --exit-code 1 /workspace

  echo "== Security: configuration policy =="
  run_trivy config --severity HIGH,CRITICAL --exit-code 1 /workspace

  echo "== Security: backend production image vulnerabilities =="
  run_trivy image --scanners vuln --ignore-unfixed --severity CRITICAL --exit-code 1 "$BACKEND_RUNTIME_IMAGE"

  echo "== Security: frontend production image vulnerabilities =="
  run_trivy image --scanners vuln --ignore-unfixed --severity CRITICAL --exit-code 1 "$FRONTEND_RUNTIME_IMAGE"

  echo "[OK] Security scans passed."
fi

echo
echo "Pre-deployment checks passed."
