#!/usr/bin/env bash
set -Eeuo pipefail

DOCKER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DOCKER_DIR"
source ./scripts/env.sh

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

[[ "$ENVIRONMENT" == "production" ]] || fail "Production deployment requires docker/.env with ENVIRONMENT=production."

TAG="${1:-}"
REGISTRY="${2:-}"
[[ -n "$TAG" ]] || fail "Usage: $0 <image-tag> <image-registry>"
[[ "$TAG" =~ ^[A-Za-z0-9._-]+$ ]] || fail "Invalid image tag: $TAG"
[[ -n "$REGISTRY" ]] || fail "Image registry is required."
REGISTRY="${REGISTRY%/}"

export BACKEND_IMAGE="$REGISTRY/zahlmeister-backend:$TAG"
export FRONTEND_IMAGE="$REGISTRY/zahlmeister-frontend:$TAG"

COMPOSE=(docker compose "${COMPOSE_ENV_ARGS[@]}" -f "$DOCKER_DIR/compose.prod.yml")

wait_service() {
  local service="$1"
  local timeout="${2:-180}"
  local started now cid status
  started="$(date +%s)"
  while true; do
    cid="$("${COMPOSE[@]}" ps -q "$service" 2>/dev/null || true)"
    if [[ -n "$cid" ]]; then
      status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || true)"
      case "$status" in
        healthy|running)
          echo "[OK] $service: $status"
          return 0
          ;;
        unhealthy|exited|dead)
          fail "$service became $status"
          ;;
      esac
    fi
    now="$(date +%s)"
    if (( now - started >= timeout )); then
      fail "Timeout waiting for $service"
    fi
    sleep 2
  done
}

on_error() {
  local rc=$?
  echo >&2
  echo "ERROR: Production deployment failed (exit $rc)." >&2
  echo "Database changes are not rolled back automatically." >&2
  "${COMPOSE[@]}" ps >&2 || true
  "${COMPOSE[@]}" logs --tail=100 backend worker frontend >&2 || true
  exit "$rc"
}
trap on_error ERR

check_env_parity
"${COMPOSE[@]}" config -q

PROXY_NETWORK_VALUE="$(env_value PROXY_NETWORK solvate_proxy)"
docker network inspect "$PROXY_NETWORK_VALUE" >/dev/null 2>&1 || fail "Docker network '$PROXY_NETWORK_VALUE' does not exist."

echo "Zahlmeister production deployment"
echo "Image tag: $TAG"
echo "Registry : $REGISTRY"

echo "Pulling immutable application images..."
"${COMPOSE[@]}" pull backend frontend

echo "Starting PostgreSQL..."
"${COMPOSE[@]}" up -d db
wait_service db

echo "Creating verified pre-deployment backup..."
ZM_COMPOSE_FILE="$DOCKER_DIR/compose.prod.yml" \
ZM_BACKUP_PREFIX="pre_deploy_${TAG:0:12}" \
  "$DOCKER_DIR/scripts/backup.sh" >/dev/null
echo "[OK] Backup completed."

echo "Stopping application services..."
"${COMPOSE[@]}" stop frontend backend worker || true

echo "Applying database bootstrap/migrations with the new backend image..."
"${COMPOSE[@]}" run --rm --no-deps bootstrap

echo "Starting worker and backend from immutable images..."
"${COMPOSE[@]}" up -d --no-build --no-deps worker backend
wait_service worker
wait_service backend

echo "Starting frontend from immutable image..."
"${COMPOSE[@]}" up -d --no-build --no-deps frontend
wait_service frontend

for service in backend worker; do
  cid="$("${COMPOSE[@]}" ps -q "$service")"
  running_image="$(docker inspect --format '{{.Config.Image}}' "$cid")"
  [[ "$running_image" == "$BACKEND_IMAGE" ]] || fail "$service runs '$running_image', expected '$BACKEND_IMAGE'."
done
frontend_cid="$("${COMPOSE[@]}" ps -q frontend)"
frontend_image="$(docker inspect --format '{{.Config.Image}}' "$frontend_cid")"
[[ "$frontend_image" == "$FRONTEND_IMAGE" ]] || fail "frontend runs '$frontend_image', expected '$FRONTEND_IMAGE'."

printf '%s\n' "$TAG" > .deployed-image-tag
printf '%s\n' "$REGISTRY" > .deployed-image-registry

trap - ERR
echo "[OK] Deployment completed successfully."
echo "[OK] Running image tag: $TAG"
