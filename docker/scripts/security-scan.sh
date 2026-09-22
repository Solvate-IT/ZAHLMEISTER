#!/usr/bin/env bash
set -euo pipefail

DOCKER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT_DIR="$(cd "$DOCKER_DIR/.." && pwd)"
TRIVY_IMAGE="${TRIVY_IMAGE:-aquasec/trivy:0.74.0}"
IMAGE_TAG="${IMAGE_TAG:-ci-runtime}"
BACKEND_IMAGE="${BACKEND_RUNTIME_IMAGE:-zahlmeister-backend:${IMAGE_TAG}}"
FRONTEND_IMAGE="${FRONTEND_RUNTIME_IMAGE:-zahlmeister-frontend:${IMAGE_TAG}}"
CACHE_DIR="${TRIVY_CACHE_DIR:-$DOCKER_DIR/.trivy-cache}"

mkdir -p "$CACHE_DIR"

run_trivy() {
  docker run --rm \
    -v /var/run/docker.sock:/var/run/docker.sock:ro \
    -v "$CACHE_DIR:/root/.cache/" \
    -v "$ROOT_DIR:/workspace:ro" \
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
run_trivy image --scanners vuln --ignore-unfixed --severity CRITICAL --exit-code 1 "$BACKEND_IMAGE"

echo "== Security: frontend production image vulnerabilities =="
run_trivy image --scanners vuln --ignore-unfixed --severity CRITICAL --exit-code 1 "$FRONTEND_IMAGE"

echo "[OK] Security scans passed."
