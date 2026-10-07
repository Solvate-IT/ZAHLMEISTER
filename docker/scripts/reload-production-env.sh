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

echo "Validating production configuration..."
check_env_parity
compose config -q

echo "Recreating worker and backend with the currently deployed immutable images..."
compose up -d --no-build --no-deps --force-recreate worker backend
wait_service worker 60
wait_service backend 180

echo "Recreating frontend with the currently deployed immutable image..."
compose up -d --no-build --no-deps --force-recreate frontend
wait_service frontend 60

FRONTEND_READY=0
for _ in $(seq 1 20); do
  if compose exec -T frontend wget -qO- http://127.0.0.1:8080/ >/dev/null 2>&1; then
    FRONTEND_READY=1
    break
  fi
  sleep 1
done
[[ "$FRONTEND_READY" == "1" ]] || fail "Frontend did not become reachable after reload."

echo "[OK] Production environment reloaded without rebuilding or pulling images."
