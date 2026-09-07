#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MODE="development"
ENV_FILE="$SCRIPT_DIR/.env"
COMPOSE_FILE="$SCRIPT_DIR/compose.yml"

if [[ "${1:-}" == "--production" ]]; then
  MODE="production"
  ENV_FILE="${ZM_ENV_FILE:-$SCRIPT_DIR/.env.production}"
  COMPOSE_FILE="$SCRIPT_DIR/compose.prod.yml"
  [[ -f "$ENV_FILE" ]] || {
    echo "Production environment file not found: $ENV_FILE" >&2
    echo "Copy .env.production.example to .env.production and configure it first." >&2
    exit 1
  }
elif [[ ! -f "$ENV_FILE" ]]; then
  cp "$SCRIPT_DIR/.env.example" "$ENV_FILE"
fi

export ZM_ENV_FILE="$ENV_FILE"
export ZM_COMPOSE_FILE="$COMPOSE_FILE"

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

pause() {
  read -r -p "Press Enter to continue..." _
}

start_stack() { compose up -d --build; }
stop_stack() { compose down; }
clean_rebuild() { compose down --remove-orphans; compose build --no-cache; compose up -d; }
status_stack() { compose ps; }
show_logs() { compose logs -f --tail=200; }
predeploy() { "$SCRIPT_DIR/predeploy.sh"; }
backend_shell() { compose exec backend bash; }
frontend_shell() { compose exec frontend sh; }
migrate() { compose run --rm migrate alembic upgrade head; }
run_tests() { compose run --rm backend pytest -q; }
remove_containers() { compose down --remove-orphans; }
remove_all() { compose down --remove-orphans --volumes; }
backup_database() { "$SCRIPT_DIR/scripts/backup.sh"; }
list_backups() { ls -lh "$SCRIPT_DIR/backups"/*.dump 2>/dev/null || echo "No backups found."; }
restore_database() {
  list_backups
  read -r -p "Backup file path: " backup_file
  read -r -p "Type RESTORE to replace the current database: " confirm
  [[ "$confirm" == "RESTORE" ]] || { echo "Restore cancelled."; return; }
  "$SCRIPT_DIR/scripts/restore.sh" "$backup_file" --force
}
ops_status() { "$SCRIPT_DIR/scripts/ops-status.sh"; }
generate_secrets() { ZM_ENV_FILE="$ENV_FILE" "$SCRIPT_DIR/scripts/generate-secrets.sh"; }

while true; do
  cat <<EOF
------------------------------------------------------------
 Zahlmeister - Docker ${MODE}
------------------------------------------------------------
 1) Start stack
 2) Stop stack
 3) Clean rebuild + restart stack
 4) Status
 5) Logs
 6) Pre-deployment checks (same script as CI)
 7) Backend shell
 8) Frontend shell
 9) Run database migrations
10) Run backend tests
11) Database backup
12) List backups
13) Restore database backup
14) Operations status
15) Generate production secrets
16) Remove containers
17) Remove containers + volumes
18) Exit
------------------------------------------------------------
 Frontend: http://localhost:8080 (development) / configured APP_HOST (production)
 Backend:  /api/v1/health and /api/v1/ready
EOF
  read -r -p "Select: " choice
  case "$choice" in
    1) start_stack ;;
    2) stop_stack ;;
    3) clean_rebuild ;;
    4) status_stack; pause ;;
    5) show_logs ;;
    6) predeploy; pause ;;
    7) backend_shell ;;
    8) frontend_shell ;;
    9) migrate; pause ;;
    10) run_tests; pause ;;
    11) backup_database; pause ;;
    12) list_backups; pause ;;
    13) restore_database; pause ;;
    14) ops_status; pause ;;
    15) generate_secrets; pause ;;
    16) remove_containers ;;
    17) remove_all ;;
    18) exit 0 ;;
    *) echo "Invalid selection"; pause ;;
  esac
done
