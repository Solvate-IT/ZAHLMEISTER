#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/env.sh"

compose() {
  docker compose "${COMPOSE_ENV_ARGS[@]}" -f "$COMPOSE_FILE" "$@"
}

normalize_admin_emails() {
  printf '%s' "$1" \
    | tr ',' '\n' \
    | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' \
    | tr '[:upper:]' '[:lower:]' \
    | sed '/^$/d' \
    | sort -u
}

confirm_yes() {
  local prompt="$1" answer
  read -r -p "$prompt [Y/n]: " answer
  case "${answer:-Y}" in
    y|Y|yes|YES|Yes) return 0 ;;
    *) return 1 ;;
  esac
}

read_runtime_admins() {
  compose exec -T backend python -c 'from app.core.config import settings; print("\n".join(sorted(settings.platform_admin_emails)))' 2>/dev/null
}

ensure_runtime_configuration() {
  local configured_admins="$1" runtime_admins
  if ! runtime_admins="$(read_runtime_admins)"; then
    echo
    echo "The backend is not running, so the admin configuration cannot be checked."
    if ! confirm_yes "Start backend and worker now?"; then
      echo "No changes were made."
      exit 1
    fi
    compose up -d backend worker
    if ! runtime_admins="$(read_runtime_admins)"; then
      echo "Backend did not become available. Check Status or Logs in manage.sh." >&2
      exit 1
    fi
  fi

  runtime_admins="$(normalize_admin_emails "$runtime_admins")"
  if [[ "$configured_admins" == "$runtime_admins" ]]; then
    return
  fi

  echo
  echo "The running backend still uses an older admin configuration."
  echo "Configured now:"
  printf '  - %s\n' $configured_admins
  echo "Running now:"
  if [[ -n "$runtime_admins" ]]; then
    printf '  - %s\n' $runtime_admins
  else
    echo "  - <none>"
  fi

  if ! confirm_yes "Apply the current configuration now?"; then
    echo "No changes were made."
    exit 1
  fi

  compose up -d --force-recreate backend worker
  if ! runtime_admins="$(read_runtime_admins)"; then
    echo "Backend did not become available after recreation. Check Logs in manage.sh." >&2
    exit 1
  fi
  runtime_admins="$(normalize_admin_emails "$runtime_admins")"
  if [[ "$configured_admins" != "$runtime_admins" ]]; then
    echo "The admin configuration is still inconsistent. No password was changed." >&2
    exit 1
  fi
  echo "Current admin configuration is active."
}

configured_admins="$(normalize_admin_emails "$(env_value PLATFORM_ADMIN_EMAILS)")"
if [[ -z "$configured_admins" ]]; then
  echo "No platform admin email is configured for ${ENVIRONMENT}." >&2
  exit 1
fi

mapfile -t admin_list <<<"$configured_admins"

echo "------------------------------------------------------------"
echo " Zahlmeister - Platform Admin Access"
echo "------------------------------------------------------------"
echo " Environment: ${ENVIRONMENT}"
echo " Configuration: ${BASE_ENV_FILE##*/}"
echo

ensure_runtime_configuration "$configured_admins"

if (( ${#admin_list[@]} == 1 )); then
  admin_email="${admin_list[0]}"
  echo " Admin email: ${admin_email}"
else
  echo "Choose the admin account:"
  for i in "${!admin_list[@]}"; do
    printf ' %d) %s\n' "$((i + 1))" "${admin_list[$i]}"
  done
  read -r -p "Selection: " selection
  if ! [[ "$selection" =~ ^[0-9]+$ ]] || (( selection < 1 || selection > ${#admin_list[@]} )); then
    echo "Invalid selection. No changes were made." >&2
    exit 1
  fi
  admin_email="${admin_list[$((selection - 1))]}"
fi

if [[ "$ENVIRONMENT" == "production" ]]; then
  echo
  echo "WARNING: This changes access to the PRODUCTION platform administration."
  if ! confirm_yes "Continue for ${admin_email}?"; then
    echo "No changes were made."
    exit 0
  fi
fi

compose exec -e ZM_PLATFORM_ADMIN_EMAIL="$admin_email" backend python -c '
import asyncio
import getpass
import os

from app.services.platform_admin import set_platform_admin_password

email = os.environ["ZM_PLATFORM_ADMIN_EMAIL"]
password = getpass.getpass("New password (minimum 16 characters): ")
if len(password) < 16:
    raise SystemExit("Password must be at least 16 characters.")
confirmation = getpass.getpass("Repeat password: ")
if password != confirmation:
    raise SystemExit("Passwords do not match.")

try:
    asyncio.run(set_platform_admin_password(email, password))
except ValueError as exc:
    raise SystemExit(str(exc)) from exc

print(f"Platform admin access updated for {email}.")
print("Existing admin sessions for this account were invalidated.")
'
