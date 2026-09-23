#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DOCKER_DIR="$SCRIPT_DIR"
source "$SCRIPT_DIR/scripts/env.sh"

compose() {
  docker compose "${COMPOSE_ENV_ARGS[@]}" -f "$COMPOSE_FILE" "$@"
}

pause() { read -r -p "Press Enter to continue..." _; }

start_stack() {
  if [[ "$ENVIRONMENT" == "production" ]]; then
    compose start
  else
    compose up -d
  fi
}

stop_stack() {
  if [[ "$ENVIRONMENT" == "production" ]]; then
    compose stop
  else
    compose down
  fi
}

clean_build() {
  if [[ "$ENVIRONMENT" == "production" ]]; then
    echo "ERROR: Production images are built, tested and deployed only by the main-branch GitHub Action." >&2
    return 1
  fi
  compose down --remove-orphans
  compose build --no-cache
  compose up -d
}

status_stack() { compose ps; }
show_logs() { compose logs -f --tail=200; }
predeploy() { ZM_PRIVATE_ENV_FILE="$PRIVATE_ENV_FILE" "$SCRIPT_DIR/scripts/test.sh" all; }
backend_shell() { compose exec backend bash; }
frontend_shell() { compose exec frontend sh; }

reload_environment() {
  [[ "$ENVIRONMENT" == "production" ]] || {
    echo "ERROR: Reload .env is a production operation." >&2
    return 1
  }

  "$SCRIPT_DIR/scripts/reload-production-env.sh"
}

health_check() {
  local failed=0
  local worker_cid

  echo "== Production health check =="

  if compose exec -T db pg_isready -U zahlmeister -d zahlmeister >/dev/null 2>&1; then
    echo "[OK] db"
  else
    echo "[FAIL] db" >&2
    failed=1
  fi

  if compose exec -T backend python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/ready', timeout=3)" >/dev/null 2>&1; then
    echo "[OK] backend /ready"
  else
    echo "[FAIL] backend /ready" >&2
    failed=1
  fi

  worker_cid="$(compose ps -q worker 2>/dev/null || true)"
  if [[ -n "$worker_cid" ]] && [[ "$(docker inspect --format '{{.State.Running}}' "$worker_cid" 2>/dev/null || true)" == "true" ]]; then
    echo "[OK] worker"
  else
    echo "[FAIL] worker" >&2
    failed=1
  fi

  if compose exec -T frontend wget -qO- http://127.0.0.1:8080/ >/dev/null 2>&1; then
    echo "[OK] frontend"
  else
    echo "[FAIL] frontend" >&2
    failed=1
  fi

  return "$failed"
}

run_tests() {
  if [[ "$ENVIRONMENT" == "production" ]]; then
    echo "ERROR: Tests are run from isolated test images, not inside the production stack." >&2
    return 1
  fi

  local backend_test_image="zahlmeister-backend-test:local"
  local frontend_test_image="zahlmeister-frontend-test:local"

  (
    cd "$PROJECT_DIR"
    echo "== Building backend test image =="
    docker build --target test -f "$SCRIPT_DIR/backend.Dockerfile" -t "$backend_test_image" .
    echo "== Running backend tests =="
    docker run --rm \
      -e ENVIRONMENT=test \
      -e READINESS_REQUIRE_WORKER=false \
      "$backend_test_image" \
      sh -c 'ruff check app tests && python -m pytest -q'

    echo "== Building frontend test image and running frontend tests =="
    docker build --target test -f "$SCRIPT_DIR/frontend.Dockerfile" -t "$frontend_test_image" .
  )

  "$SCRIPT_DIR/scripts/platform-admin-access.test.sh"
}

production_menu() {
  local frontend_url choice
  frontend_url="$(env_value PUBLIC_APP_URL "https://zahlmeister.solvate.at")"

  cat <<EOF
------------------------------------------------------------
 Zahlmeister - Docker production
------------------------------------------------------------
 1) Start Stack
 2) Stop Stack
 3) Status
 4) Logs
 5) Reload .env / Recreate App Services
 6) Health Check
 7) Backend Shell
 8) Frontend Shell
 q) Quit
------------------------------------------------------------
 Frontend: ${frontend_url}
EOF
  read -r -p "Select: " choice

  case "$choice" in
    1) start_stack ;;
    2) stop_stack ;;
    3) status_stack; pause ;;
    4) show_logs ;;
    5) if ! reload_environment; then echo "Reload failed." >&2; fi; pause ;;
    6) if ! health_check; then echo "Health check failed." >&2; fi; pause ;;
    7) backend_shell ;;
    8) frontend_shell ;;
    q|Q) exit 0 ;;
    *) echo "Invalid selection"; pause ;;
  esac
}

development_menu() {
  local frontend_port frontend_url mailpit_port choice
  frontend_port="$(env_value FRONTEND_PORT 3003)"
  frontend_url="$(env_value PUBLIC_APP_URL "http://localhost:${frontend_port}")"
  mailpit_port="$(env_value MAILPIT_PORT 8028)"

  cat <<EOF
------------------------------------------------------------
 Zahlmeister - Docker development
------------------------------------------------------------
 1) Start
 2) Stop
 3) Clean Build
 4) Status
 5) Logs
 6) Pre-Deployment Checks
 7) Backend Shell
 8) Frontend Shell
 9) Tests
 q) Quit
------------------------------------------------------------
 Frontend: ${frontend_url}
 Backend:  /api/v1/health and /api/v1/ready
 Mailpit:  http://localhost:${mailpit_port}
EOF
  read -r -p "Select: " choice

  case "$choice" in
    1) start_stack ;;
    2) stop_stack ;;
    3) clean_build ;;
    4) status_stack; pause ;;
    5) show_logs ;;
    6) predeploy; pause ;;
    7) backend_shell ;;
    8) frontend_shell ;;
    9) run_tests; pause ;;
    q|Q) exit 0 ;;
    *) echo "Invalid selection"; pause ;;
  esac
}

while true; do
  if [[ "$ENVIRONMENT" == "production" ]]; then
    production_menu
  else
    development_menu
  fi
done
