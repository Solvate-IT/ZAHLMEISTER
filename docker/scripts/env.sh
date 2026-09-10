#!/usr/bin/env bash
set -euo pipefail

DOCKER_DIR="${DOCKER_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PRIVATE_ENV_FILE="${ZM_PRIVATE_ENV_FILE:-$DOCKER_DIR/.env}"
DEV_ENV_FILE="$DOCKER_DIR/.env.development"
PROD_ENV_FILE="$DOCKER_DIR/.env.production"

read_env_value_from_file() {
  local file="$1" key="$2" value
  value="$(sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//p" "$file" | tail -n 1)"
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"
  printf '%s' "$value"
}

extract_env_keys() {
  sed -nE 's/^[[:space:]]*#?[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=.*$/\1/p' "$1" | sort -u
}

check_env_parity() {
  [[ -f "$DEV_ENV_FILE" ]] || { echo "Missing environment file: $DEV_ENV_FILE" >&2; exit 1; }
  [[ -f "$PROD_ENV_FILE" ]] || { echo "Missing environment file: $PROD_ENV_FILE" >&2; exit 1; }

  local missing_prod missing_dev
  missing_prod="$(comm -23 <(extract_env_keys "$DEV_ENV_FILE") <(extract_env_keys "$PROD_ENV_FILE"))"
  missing_dev="$(comm -13 <(extract_env_keys "$DEV_ENV_FILE") <(extract_env_keys "$PROD_ENV_FILE"))"
  if [[ -n "$missing_prod" || -n "$missing_dev" ]]; then
    echo "Environment key mismatch between .env.development and .env.production." >&2
    [[ -z "$missing_prod" ]] || { echo "Missing in .env.production:" >&2; printf '  - %s\n' $missing_prod >&2; }
    [[ -z "$missing_dev" ]] || { echo "Missing in .env.development:" >&2; printf '  - %s\n' $missing_dev >&2; }
    echo "Add every configuration key to both environment files before continuing." >&2
    exit 1
  fi
}

[[ -f "$PRIVATE_ENV_FILE" ]] || {
  echo "Private environment file not found: $PRIVATE_ENV_FILE" >&2
  echo "Create it with ENVIRONMENT=development or ENVIRONMENT=production and private/secret overrides." >&2
  exit 1
}

ENVIRONMENT="$(read_env_value_from_file "$PRIVATE_ENV_FILE" ENVIRONMENT)"
case "$ENVIRONMENT" in
  development)
    BASE_ENV_FILE="$DEV_ENV_FILE"
    COMPOSE_FILE="$DOCKER_DIR/compose.yml"
    ;;
  production)
    BASE_ENV_FILE="$PROD_ENV_FILE"
    COMPOSE_FILE="$DOCKER_DIR/compose.prod.yml"
    ;;
  *)
    echo "ENVIRONMENT in $PRIVATE_ENV_FILE must be development or production." >&2
    exit 1
    ;;
esac

check_env_parity

base_environment="$(read_env_value_from_file "$BASE_ENV_FILE" ENVIRONMENT)"
[[ "$base_environment" == "$ENVIRONMENT" ]] || {
  echo "ENVIRONMENT mismatch: $BASE_ENV_FILE declares '$base_environment', expected '$ENVIRONMENT'." >&2
  exit 1
}

COMPOSE_ENV_ARGS=(--env-file "$BASE_ENV_FILE" --env-file "$PRIVATE_ENV_FILE")

has_env_key() {
  grep -qE "^[[:space:]]*$1[[:space:]]*=" "$2"
}

env_value() {
  local key="$1" fallback="${2:-}" value
  if has_env_key "$key" "$PRIVATE_ENV_FILE"; then
    value="$(read_env_value_from_file "$PRIVATE_ENV_FILE" "$key")"
  else
    value="$(read_env_value_from_file "$BASE_ENV_FILE" "$key")"
  fi
  printf '%s' "${value:-$fallback}"
}

export ENVIRONMENT BASE_ENV_FILE PRIVATE_ENV_FILE COMPOSE_FILE
