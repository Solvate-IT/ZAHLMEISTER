#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${PREDEPLOY_ENV_FILE:-$SCRIPT_DIR/.env}"
PROD_FILE="$SCRIPT_DIR/compose.prod.yml"
IMAGE_TAG="${IMAGE_TAG:-predeploy}"
BACKEND_TEST_IMAGE="zahlmeister-backend-test:${IMAGE_TAG}"
FRONTEND_TEST_IMAGE="zahlmeister-frontend-test:${IMAGE_TAG}"

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$SCRIPT_DIR/.env.example" "$ENV_FILE"
fi

cd "$PROJECT_DIR"

echo "== Zahlmeister pre-deployment checks =="
echo "The same script is intended to run locally and in GitHub Actions."

echo
echo "[1/8] Checking required runtime files..."
required_files=(
  "backend/pyproject.toml"
  "backend/app/main.py"
  "backend/app/core/config.py"
  "backend/app/core/observability.py"
  "backend/app/api/router.py"
  "backend/app/api/public_router.py"
  "backend/app/api/deps.py"
  "backend/app/api/routes/api_access.py"
  "backend/app/api/routes/public_api.py"
  "backend/app/api/routes/auth.py"
  "backend/app/api/routes/account.py"
  "backend/app/api/routes/bank_imports.py"
  "backend/app/api/routes/bank_sync.py"
  "backend/app/api/routes/collections.py"
  "backend/app/api/routes/communications.py"
  "backend/app/api/routes/communication_settings.py"
  "backend/app/api/routes/imports.py"
  "backend/app/api/routes/participant_lists.py"
  "backend/app/api/routes/public_contact.py"
  "backend/app/api/routes/public_payments.py"
  "backend/app/api/routes/webhooks.py"
  "backend/app/models/channel_strategy.py"
  "backend/app/schemas/api_access.py"
  "backend/app/schemas/communications.py"
  "backend/app/schemas/workflow.py"
  "backend/app/services/api_access.py"
  "backend/app/services/central_mail.py"
  "backend/app/services/channel_config.py"
  "backend/app/services/channel_strategy.py"
  "backend/app/services/communications.py"
  "backend/app/services/infobip.py"
  "backend/app/services/message_dispatch.py"
  "backend/app/services/microsoft365.py"
  "backend/app/worker.py"
  "backend/alembic.ini"
  "backend/alembic/versions/0013_public_api_access.py"
  "backend/alembic/versions/0014_platform_subscriptions.py"
  "backend/alembic/versions/0015_channel_strategy.py"
  "backend/tests/test_channel_strategy.py"
  "frontend/package.json"
  "frontend/next.config.ts"
  "frontend/tsconfig.json"
  "frontend/src/app/layout.tsx"
  "frontend/src/app/page.tsx"
  "frontend/src/app/app/page.tsx"
  "frontend/src/app/payment/page.tsx"
  "frontend/src/app/action/page.tsx"
  "frontend/src/lib/api.ts"
  "frontend/src/lib/native.ts"
  "frontend/src/lib/session.ts"
  "frontend/src/lib/i18n.tsx"
  "frontend/src/lib/types.ts"
  "frontend/src/locales/integrations.ts"
  "frontend/src/components/Workspace.tsx"
  "frontend/src/components/PublicPayment.tsx"
  "frontend/src/components/AccountAction.tsx"
  "frontend/src/components/workspace/CollectionsPage.tsx"
  "frontend/src/components/workspace/CommunicationSettingsPanel.tsx"
  "frontend/src/components/workspace/ListsPage.tsx"
  "frontend/public/brand/logo.png"
  "frontend/public/brand/app_icon.png"
  "frontend/public/manifest.webmanifest"
  "mobile/package.json"
  "mobile/capacitor.config.ts"
  "mobile/tool/bootstrap_mobile.sh"
  "mobile/assets/brand/app_icon.png"
  "mobile/mobile-links/assetlinks.json.example"
  "mobile/mobile-links/apple-app-site-association.example"
  "docker/.env.production.example"
  "docker/compose.prod.yml"
  "docker/backend.Dockerfile"
  "docker/frontend.Dockerfile"
  "docker/nginx.conf"
  "docker/INTEGRATIONS.md"
  "docker/OPERATIONS.md"
  "docker/secrets/README.md"
  "docker/secrets/production/.gitkeep"
  "docker/backups/.gitkeep"
  "docker/scripts/common.sh"
  "docker/scripts/backup.sh"
  "docker/scripts/restore.sh"
  "docker/scripts/generate-secrets.sh"
  "docker/scripts/ops-status.sh"
)
for file in "${required_files[@]}"; do
  [[ -f "$file" ]] || { echo "Missing required file: $file"; exit 1; }
done

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo
echo "[2/8] Checking that required runtime files are tracked by Git..."
  for file in "${required_files[@]}"; do
    git ls-files --error-unmatch "$file" >/dev/null 2>&1 || {
      echo "Required runtime file is not tracked by Git: $file"
      git check-ignore -v "$file" || true
      exit 1
    }
  done
else
  echo
echo "[2/8] Git tracking check skipped (not inside a Git work tree)."
fi

echo
echo "[3/8] Validating Compose and shell scripts..."
docker compose --env-file "$ENV_FILE" -f "$PROD_FILE" config -q
docker compose --env-file "$ENV_FILE" -f "$SCRIPT_DIR/compose.yml" config -q
bash -n "$SCRIPT_DIR/manage.sh" "$SCRIPT_DIR/predeploy.sh" "$SCRIPT_DIR"/scripts/*.sh "$PROJECT_DIR/mobile/tool/bootstrap_mobile.sh"

echo
echo "[4/8] Building and running dedicated test stages..."
docker build --target test -f "$SCRIPT_DIR/backend.Dockerfile" -t "$BACKEND_TEST_IMAGE" .
docker run --rm \
  -e ENVIRONMENT=test \
  -e READINESS_REQUIRE_WORKER=false \
  "$BACKEND_TEST_IMAGE" \
  sh -c 'ruff check --select E4,E7,E9,F app tests && pytest -q'

docker build --target test -f "$SCRIPT_DIR/frontend.Dockerfile" -t "$FRONTEND_TEST_IMAGE" .

echo
echo "[5/8] Building the actual production images..."
IMAGE_TAG="$IMAGE_TAG" docker compose --env-file "$ENV_FILE" -f "$PROD_FILE" build backend frontend

APP_RUNTIME_UID_VALUE="$(sed -n 's/^APP_RUNTIME_UID=//p' "$ENV_FILE" | tail -n 1 | tr -d '"')"
APP_RUNTIME_UID_VALUE="${APP_RUNTIME_UID_VALUE:-10001}"

echo
echo "[6/8] Checking final runtime images..."
IMAGE_TAG="$IMAGE_TAG" docker compose --env-file "$ENV_FILE" -f "$PROD_FILE" run --rm --no-deps \
  -e EXPECTED_RUNTIME_UID="$APP_RUNTIME_UID_VALUE" backend \
  sh -c '
    command -v tesseract >/dev/null &&
    command -v pdftoppm >/dev/null &&
    command -v qrencode >/dev/null &&
    python -c "import reportlab" &&
    tesseract --list-langs 2>/dev/null | grep -qx Latin &&
    tesseract --list-langs 2>/dev/null | grep -qx ell &&
    tesseract --list-langs 2>/dev/null | grep -qx bul &&
    test "$(id -u)" = "$EXPECTED_RUNTIME_UID" &&
    test ! -d /app/tests &&
    ! command -v pytest >/dev/null &&
    ! command -v ruff >/dev/null
  '

IMAGE_TAG="$IMAGE_TAG" docker compose --env-file "$ENV_FILE" -f "$PROD_FILE" run --rm --no-deps \
  --entrypoint sh frontend -c '
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

echo
echo "[7/8] Checking production configuration and Capacitor source..."
IMAGE_TAG="$IMAGE_TAG" docker compose --env-file "$ENV_FILE" -f "$PROD_FILE" run --rm --no-deps backend \
  python -c 'from app.core.config import settings; assert settings.environment == "production"'
grep -q 'appId: "at.solvate.zahlmeister"' mobile/capacitor.config.ts
grep -q 'webDir: "../frontend/out"' mobile/capacitor.config.ts
! grep -R --exclude-dir=node_modules -nE 'flutter|dart' frontend mobile docker/frontend.Dockerfile docker/frontend.Dockerfile.dev docker/compose.yml 2>/dev/null || {
  echo "Flutter/Dart references remain in the new frontend/mobile runtime paths." >&2
  exit 1
}

echo
echo "[8/8] Checking that production secrets and backups are excluded from Git..."
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if git ls-files 'docker/secrets/production/*' 'docker/backups/*' | grep -vE '/\.gitkeep$' | grep -q .; then
    echo "Production secrets or backups must not be tracked by Git." >&2
    exit 1
  fi
fi

echo
echo "Pre-deployment checks passed."
