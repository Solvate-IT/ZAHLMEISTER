#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$SCRIPT_DIR"
source "$SCRIPT_DIR/scripts/env.sh"

compose() {
  docker compose "${COMPOSE_ENV_ARGS[@]}" -f "$COMPOSE_FILE" "$@"
}

pause() { read -r -p "Press Enter to continue..." _; }
start_stack() { compose up -d; }
stop_stack() { compose down; }
clean_build() {
  compose down --remove-orphans
  compose build --no-cache
  compose up -d
}
status_stack() { compose ps; }
show_logs() { compose logs -f --tail=200; }
predeploy() { ZM_PRIVATE_ENV_FILE="$PRIVATE_ENV_FILE" "$SCRIPT_DIR/predeploy.sh"; }
backend_shell() { compose exec backend bash; }
frontend_shell() { compose exec frontend sh; }
apply_schema() { compose run --rm bootstrap; }
run_tests() { compose run --rm backend pytest -q; }
normalize_admin_emails() {
  printf '%s' "$1" \
    | tr ',' '\n' \
    | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' \
    | tr '[:upper:]' '[:lower:]' \
    | sed '/^$/d' \
    | sort -u
}
platform_admin_access() {
  local configured_admins runtime_admins
  configured_admins="$(normalize_admin_emails "$(env_value PLATFORM_ADMIN_EMAILS)")"
  if [[ -z "$configured_admins" ]]; then
    echo "No platform admin emails are configured in PLATFORM_ADMIN_EMAILS." >&2
    return 1
  fi

  echo "Configured platform admin emails (${BASE_ENV_FILE##*/}):"
  printf '  - %s\n' $configured_admins

  if ! runtime_admins="$(compose exec -T backend python -c 'from app.core.config import settings; print("\n".join(sorted(settings.platform_admin_emails)))' 2>/dev/null)"; then
    echo "Backend container is not running or its configuration cannot be read." >&2
    echo "Start the stack first, then retry Platform Admin Access." >&2
    return 1
  fi
  runtime_admins="$(normalize_admin_emails "$runtime_admins")"

  if [[ "$configured_admins" != "$runtime_admins" ]]; then
    echo >&2
    echo "Platform admin configuration mismatch." >&2
    echo "The running backend still uses different PLATFORM_ADMIN_EMAILS values:" >&2
    if [[ -n "$runtime_admins" ]]; then
      printf '  - %s\n' $runtime_admins >&2
    else
      echo "  - <none>" >&2
    fi
    echo >&2
    echo "Recreate the backend and worker with the current environment, then retry:" >&2
    printf '  docker compose' >&2
    printf ' %q' "${COMPOSE_ENV_ARGS[@]}" >&2
    printf ' -f %q up -d --force-recreate backend worker\n' "$COMPOSE_FILE" >&2
    return 1
  fi

  compose exec backend python -c '
import asyncio
import getpass

from app.core.config import settings
from app.services.platform_admin import set_platform_admin_password

admins = sorted(settings.platform_admin_emails)
if not admins:
    raise SystemExit("No platform admin emails are configured in PLATFORM_ADMIN_EMAILS.")

email = input("Admin email: ").strip()
if not email:
    raise SystemExit("No email entered.")
if email.casefold() not in settings.platform_admin_emails:
    raise SystemExit("Email is not configured in PLATFORM_ADMIN_EMAILS.")

password = getpass.getpass("New password: ")
confirmation = getpass.getpass("Repeat password: ")
if password != confirmation:
    raise SystemExit("Passwords do not match.")

try:
    asyncio.run(set_platform_admin_password(email, password))
except ValueError as exc:
    raise SystemExit(str(exc)) from exc

print("Platform admin access created or updated successfully.")
'
}

while true; do
  frontend_port="$(env_value FRONTEND_PORT 3003)"
  frontend_url="$(env_value PUBLIC_APP_URL "http://localhost:${frontend_port}")"
  mailpit_port="$(env_value MAILPIT_PORT 8028)"
  cat <<EOF
------------------------------------------------------------
 Zahlmeister - Docker ${ENVIRONMENT}
------------------------------------------------------------
 1) Start
 2) Stop
 3) Clean Build
 4) Status
 5) Logs
 6) Pre-Deployment Checks
 7) Backend Shell
 8) Frontend Shell
 9) Database Initialize / Migrate / Verify
10) Tests
11) Platform Admin Access
 q) Quit
------------------------------------------------------------
 Frontend: ${frontend_url}
 Backend:  /api/v1/health and /api/v1/ready
 Mailpit:  http://localhost:${mailpit_port} (development only)
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
    9) apply_schema; pause ;;
    10) run_tests; pause ;;
    11) platform_admin_access; pause ;;
    q|Q) exit 0 ;;
    *) echo "Invalid selection"; pause ;;
  esac
done
