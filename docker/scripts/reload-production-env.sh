#!/usr/bin/env bash
set -Eeuo pipefail

DOCKER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DOCKER_DIR"
source ./scripts/env.sh

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

[[ "$ENVIRONMENT" == "production" ]] || fail "Reload requires docker/.env with ENVIRONMENT=production."

TAG_FILE="$DOCKER_DIR/.deployed-image-tag"
REGISTRY_FILE="$DOCKER_DIR/.deployed-image-registry"
[[ -s "$TAG_FILE" && -s "$REGISTRY_FILE" ]] || fail "Deployed image metadata is missing. Run a normal production deployment first."

TAG="$(tr -d '\r\n' < "$TAG_FILE")"
REGISTRY="$(tr -d '\r\n' < "$REGISTRY_FILE")"
REGISTRY="${REGISTRY%/}"

[[ "$TAG" =~ ^[A-Za-z0-9._-]+$ ]] || fail "Invalid deployed image tag."
[[ -n "$REGISTRY" ]] || fail "Invalid deployed image registry."

export BACKEND_IMAGE="$REGISTRY/zahlmeister-backend:$TAG"
export FRONTEND_IMAGE="$REGISTRY/zahlmeister-frontend:$TAG"

COMPOSE=(docker compose "${COMPOSE_ENV_ARGS[@]}" -f "$COMPOSE_FILE")

wait_service() {
  local service="$1"
  local timeout="${2:-180}"
  local started now cid service_status

  started="$(date +%s)"
  while true; do
    cid="$("${COMPOSE[@]}" ps -q "$service" 2>/dev/null || true)"
    if [[ -n "$cid" ]]; then
      service_status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || true)"
      case "$service_status" in
        healthy|running)
          echo "[OK] $service: $service_status"
          return 0
          ;;
        unhealthy|exited|dead)
          fail "$service became $service_status"
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

echo "Validating production configuration..."
check_env_parity
"${COMPOSE[@]}" config -q

echo "Recreating worker and backend with the currently deployed immutable images..."
"${COMPOSE[@]}" up -d --no-build --no-deps --force-recreate worker backend
wait_service worker 60
wait_service backend 180

echo "Recreating frontend with the currently deployed immutable image..."
"${COMPOSE[@]}" up -d --no-build --no-deps --force-recreate frontend
wait_service frontend 60

FRONTEND_READY=0
for _ in $(seq 1 20); do
  if "${COMPOSE[@]}" exec -T frontend wget -qO- http://127.0.0.1:8080/ >/dev/null 2>&1; then
    FRONTEND_READY=1
    break
  fi
  sleep 1
done
[[ "$FRONTEND_READY" == "1" ]] || fail "Frontend did not become reachable after reload."

echo "[OK] Production environment reloaded without rebuilding or pulling images."
