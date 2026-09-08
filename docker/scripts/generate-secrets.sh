#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${ZM_ENV_FILE:-$DOCKER_DIR/.env.production}"
TARGET_DIR="${ZM_SECRETS_DIR:-$DOCKER_DIR/secrets/production}"
FORCE="${1:-}"

command -v openssl >/dev/null || { echo "openssl is required" >&2; exit 1; }
[[ -f "$ENV_FILE" ]] || { echo "Environment file not found: $ENV_FILE" >&2; exit 1; }

read_env_value() {
  local key="$1"
  local value
  value="$(sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1)"
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"
  printf '%s' "$value"
}

POSTGRES_USER="$(read_env_value POSTGRES_USER)"
POSTGRES_DB="$(read_env_value POSTGRES_DB)"
APP_RUNTIME_UID="$(read_env_value APP_RUNTIME_UID)"
APP_RUNTIME_GID="$(read_env_value APP_RUNTIME_GID)"
APP_RUNTIME_UID="${APP_RUNTIME_UID:-10001}"
APP_RUNTIME_GID="${APP_RUNTIME_GID:-10001}"
[[ -n "$POSTGRES_USER" ]] || { echo "POSTGRES_USER is required in $ENV_FILE" >&2; exit 1; }
[[ -n "$POSTGRES_DB" ]] || { echo "POSTGRES_DB is required in $ENV_FILE" >&2; exit 1; }
[[ "$APP_RUNTIME_UID" =~ ^[0-9]+$ && "$APP_RUNTIME_UID" != "0" ]] || {
  echo "APP_RUNTIME_UID must be a non-root numeric UID" >&2
  exit 1
}
[[ "$APP_RUNTIME_GID" =~ ^[0-9]+$ && "$APP_RUNTIME_GID" != "0" ]] || {
  echo "APP_RUNTIME_GID must be a non-root numeric GID" >&2
  exit 1
}
if [[ "$(id -u)" != "0" && ( "$(id -u)" != "$APP_RUNTIME_UID" || "$(id -g)" != "$APP_RUNTIME_GID" ) ]]; then
  echo "Run this script as root, or set APP_RUNTIME_UID/GID to the current deployment user." >&2
  exit 1
fi

mkdir -p "$TARGET_DIR"
chmod 750 "$TARGET_DIR"
umask 077

read_existing_secret() {
  local path="$1"
  [[ -f "$path" ]] || { echo "Existing secret is not a regular file: $path" >&2; exit 1; }
  local value
  value="$(tr -d '\r\n' < "$path")"
  [[ -n "$value" ]] || { echo "Existing secret is empty: $path" >&2; exit 1; }
  printf '%s' "$value"
}

write_secret() {
  local path="$1"
  local value="$2"
  if [[ -e "$path" && "$FORCE" != "--force" ]]; then
    [[ -f "$path" ]] || { echo "Existing secret is not a regular file: $path" >&2; exit 1; }
    echo "Keeping existing secret: $path"
    return
  fi
  printf '%s\n' "$value" > "$path"
  chmod 640 "$path"
}

if [[ -e "$TARGET_DIR/postgres_password" && "$FORCE" != "--force" ]]; then
  postgres_password="$(read_existing_secret "$TARGET_DIR/postgres_password")"
else
  postgres_password="$(openssl rand -hex 32)"
fi
app_secret="$(openssl rand -hex 48)"
monitoring_token="$(openssl rand -hex 32)"
mollie_billing_webhook_secret="$(openssl rand -hex 32)"
database_url="postgresql+asyncpg://${POSTGRES_USER}:${postgres_password}@db:5432/${POSTGRES_DB}"

write_secret "$TARGET_DIR/postgres_password" "$postgres_password"
write_secret "$TARGET_DIR/database_url" "$database_url"
write_secret "$TARGET_DIR/app_secret" "$app_secret"
write_secret "$TARGET_DIR/monitoring_token" "$monitoring_token"
write_secret "$TARGET_DIR/mollie_billing_webhook_secret" "$mollie_billing_webhook_secret"

if [[ "$(id -u)" == "0" ]]; then
  chown -R "$APP_RUNTIME_UID:$APP_RUNTIME_GID" "$TARGET_DIR"
fi
chmod 750 "$TARGET_DIR"
find "$TARGET_DIR" -maxdepth 1 -type f ! -name '.gitkeep' -exec chmod 640 {} +

echo "Production secrets are available in $TARGET_DIR"
echo "Runtime owner: ${APP_RUNTIME_UID}:${APP_RUNTIME_GID}"
echo "Existing secrets were preserved unless --force was specified."
echo "A newly created database_url always uses the actual preserved or rotated postgres_password."
echo "Create platform_smtp_password and mollie_billing_api_key there when those integrations are enabled."
echo "Configure Mollie's Sales Invoice webhook with mollie_billing_webhook_secret."
