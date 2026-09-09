#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="development"
ENV_FILE="$SCRIPT_DIR/.env"
COMPOSE_FILE="$SCRIPT_DIR/compose.yml"

check_env_keys() {
  local example_file="$1"
  local env_file="$2"
  local label="$3"
  local line key
  local -a missing=()

  [[ -f "$example_file" && -f "$env_file" ]] || return 0

  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue
    key="${line%%=*}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    grep -qE "^${key}=" "$env_file" || missing+=("$key")
  done < "$example_file"

  if (( ${#missing[@]} > 0 )); then
    echo "WARNING: $label environment is missing variables from $(basename "$example_file"):" >&2
    printf '  - %s\n' "${missing[@]}" >&2
    echo "Add the missing variables to $env_file. Existing values are never changed automatically." >&2
    echo >&2
  fi
}

if [[ "${1:-}" == "--production" ]]; then
  MODE="production"
  ENV_FILE="${ZM_ENV_FILE:-$SCRIPT_DIR/.env.production}"
  COMPOSE_FILE="$SCRIPT_DIR/compose.prod.yml"
  [[ -f "$ENV_FILE" ]] || {
    echo "Production environment file not found: $ENV_FILE" >&2
    echo "Copy .env.production.example to .env.production and configure it first." >&2
    exit 1
  }
  check_env_keys "$SCRIPT_DIR/.env.production.example" "$ENV_FILE" "production"
elif [[ ! -f "$ENV_FILE" ]]; then
  cp "$SCRIPT_DIR/.env.example" "$ENV_FILE"
else
  check_env_keys "$SCRIPT_DIR/.env.example" "$ENV_FILE" "development"
fi

export ZM_ENV_FILE="$ENV_FILE"
export ZM_COMPOSE_FILE="$COMPOSE_FILE"

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

env_value() {
  local key="$1" fallback="$2" value
  value="$(grep -E "^${key}=" "$ENV_FILE" | tail -n1 | cut -d= -f2- || true)"
  printf '%s' "${value:-$fallback}"
}

pause() { read -r -p "Press Enter to continue..." _; }
start_stack() { compose up -d --build; }
stop_stack() { compose down; }
clean_rebuild() {
  if [[ "$MODE" == "development" ]]; then
    compose down --remove-orphans --volumes
  else
    compose down --remove-orphans
  fi
  compose build --no-cache
  compose up -d
}
status_stack() { compose ps; }
show_logs() { compose logs -f --tail=200; }
predeploy() { "$SCRIPT_DIR/predeploy.sh"; }
backend_shell() { compose exec backend bash; }
frontend_shell() { compose exec frontend sh; }
apply_schema() { compose run --rm bootstrap; }
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
setup_platform_admin() { compose run --rm backend python -m app.platform_admin_cli; }

while true; do
  frontend_port="$(env_value FRONTEND_PORT 3003)"
  mailpit_port="$(env_value MAILPIT_PORT 8028)"
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
 9) Initialize/verify database schema
10) Run backend tests
11) Database backup
12) List backups
13) Restore database backup
14) Operations status
15) Generate production secrets
16) Remove containers
17) Remove containers + volumes
18) Set/reset platform admin password
19) Exit
------------------------------------------------------------
 Frontend: http://localhost:${frontend_port} (development) / configured APP_HOST (production)
 Backend:  /api/v1/health and /api/v1/ready
 Mailpit:  http://localhost:${mailpit_port} (development only)
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
    9) apply_schema; pause ;;
    10) run_tests; pause ;;
    11) backup_database; pause ;;
    12) list_backups; pause ;;
    13) restore_database; pause ;;
    14) ops_status; pause ;;
    15) generate_secrets; pause ;;
    16) remove_containers ;;
    17) remove_all ;;
    18) setup_platform_admin; pause ;;
    19) exit 0 ;;
    *) echo "Invalid selection"; pause ;;
  esac
done
