#!/usr/bin/env bash
set -euo pipefail

DOCKER_DIR="${DOCKER_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PRIVATE_ENV_FILE="${ZM_PRIVATE_ENV_FILE:-$DOCKER_DIR/.env}"
DEV_ENV_FILE="$DOCKER_DIR/.env.development"
PROD_ENV_FILE="$DOCKER_DIR/.env.production"

read_env_value_from_file() {
  local file="$1" key="$2" value first last
  value="$(sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//p" "$file" | tail -n 1)"

  # Whitespace outside a dotenv value is insignificant. Trim it before
  # removing a matching pair of surrounding quotes.
  value="$(printf '%s' "$value" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')"

  if (( ${#value} >= 2 )); then
    first="${value:0:1}"
    last="${value: -1}"
    if [[ "$first" == "$last" && ( "$first" == "'" || "$first" == '"' ) ]]; then
      value="${value:1:${#value}-2}"
    fi
  fi

  printf '%s' "$value"
}

extract_env_keys() {
  sed -nE 's/^[[:space:]]*#?[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=.*$/\1/p' "$1" | sort -u
}

extract_active_env_keys() {
  sed -nE 's/^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=.*$/\1/p' "$1" | sort -u
}

extract_external_env_keys() {
  sed -nE '/external credential in \.env/ s/^[[:space:]]*#[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=.*$/\1/p' "$1" | sort -u
}

check_env_parity() {
  [[ -f "$DEV_ENV_FILE" ]] || { echo "Missing environment file: $DEV_ENV_FILE" >&2; exit 1; }
  [[ -f "$PROD_ENV_FILE" ]] || { echo "Missing environment file: $PROD_ENV_FILE" >&2; exit 1; }

  local missing_prod missing_dev external_missing_prod external_missing_dev
  missing_prod="$(comm -23 <(extract_env_keys "$DEV_ENV_FILE") <(extract_env_keys "$PROD_ENV_FILE"))"
  missing_dev="$(comm -13 <(extract_env_keys "$DEV_ENV_FILE") <(extract_env_keys "$PROD_ENV_FILE"))"
  external_missing_prod="$(comm -23 <(extract_external_env_keys "$DEV_ENV_FILE") <(extract_external_env_keys "$PROD_ENV_FILE"))"
  external_missing_dev="$(comm -13 <(extract_external_env_keys "$DEV_ENV_FILE") <(extract_external_env_keys "$PROD_ENV_FILE"))"

  if [[ -n "$missing_prod" || -n "$missing_dev" ]]; then
    echo "Environment key mismatch between .env.development and .env.production." >&2
    [[ -z "$missing_prod" ]] || { echo "Missing in .env.production:" >&2; printf '  - %s\n' $missing_prod >&2; }
    [[ -z "$missing_dev" ]] || { echo "Missing in .env.development:" >&2; printf '  - %s\n' $missing_dev >&2; }
    exit 1
  fi

  if [[ -n "$external_missing_prod" || -n "$external_missing_dev" ]]; then
    echo "External credential marker mismatch between environment files." >&2
    [[ -z "$external_missing_prod" ]] || { echo "Missing marker in .env.production:" >&2; printf '  - %s\n' $external_missing_prod >&2; }
    [[ -z "$external_missing_dev" ]] || { echo "Missing marker in .env.development:" >&2; printf '  - %s\n' $external_missing_dev >&2; }
    exit 1
  fi
}

legacy_internal_keys() {
  printf '%s\n' \
    APP_SECRET \
    DATABASE_URL \
    MONITORING_TOKEN \
    PLATFORM_ADMIN_BOOTSTRAP_PASSWORD \
    POSTGRES_PASSWORD
}

check_private_env_file() {
  local allowed actual unexpected legacy_present
  allowed="$( { printf '%s\n' ENVIRONMENT; extract_external_env_keys "$BASE_ENV_FILE"; legacy_internal_keys; } | sort -u )"
  actual="$(extract_active_env_keys "$PRIVATE_ENV_FILE")"
  unexpected="$(comm -23 <(printf '%s\n' "$actual") <(printf '%s\n' "$allowed"))"

  if [[ -n "$unexpected" ]]; then
    echo "Unexpected configuration in $PRIVATE_ENV_FILE:" >&2
    printf '  - %s\n' $unexpected >&2
    echo ".env may contain only ENVIRONMENT and external credentials documented in .env.${ENVIRONMENT}." >&2
    exit 1
  fi

  legacy_present="$(comm -12 <(printf '%s\n' "$actual") <(legacy_internal_keys | sort -u))"
  if [[ -n "$legacy_present" ]]; then
    echo "Migrated legacy internal secrets from .env into docker/secrets/${ENVIRONMENT}." >&2
    echo "You can now remove these obsolete keys from .env:" >&2
    printf '  - %s\n' $legacy_present >&2
  fi
}

[[ -f "$PRIVATE_ENV_FILE" ]] || {
  echo "Environment selector not found: $PRIVATE_ENV_FILE" >&2
  echo "Create it with ENVIRONMENT=development or ENVIRONMENT=production." >&2
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

# Load external credentials after the tracked environment-specific configuration.
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

load_layered_environment() {
  local key value

  # Docker Compose gives inherited shell variables precedence over --env-file.
  # Normalize every project-managed key into the shell so the documented
  # layering is deterministic: tracked environment first, private .env second.
  # Commented external credential markers intentionally become empty when the
  # private file does not configure them, preventing stale exported credentials
  # from silently enabling integrations.
  while IFS= read -r key; do
    [[ -n "$key" ]] || continue
    if has_env_key "$key" "$PRIVATE_ENV_FILE"; then
      value="$(read_env_value_from_file "$PRIVATE_ENV_FILE" "$key")"
    elif has_env_key "$key" "$BASE_ENV_FILE"; then
      value="$(read_env_value_from_file "$BASE_ENV_FILE" "$key")"
    else
      value=""
    fi
    printf -v "$key" '%s' "$value"
    export "$key"
  done < <({ extract_env_keys "$BASE_ENV_FILE"; extract_active_env_keys "$PRIVATE_ENV_FILE"; } | sort -u)
}

load_layered_environment

random_hex() {
  local bytes="$1"
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$bytes"
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    python3 -c "import secrets; print(secrets.token_hex($bytes))"
    return
  fi
  echo "openssl or python3 is required to generate internal secrets" >&2
  return 1
}

legacy_value() {
  local key="$1" private_file="$2"
  if [[ -f "$private_file" ]] && grep -qE "^[[:space:]]*${key}[[:space:]]*=" "$private_file"; then
    read_env_value_from_file "$private_file" "$key"
  fi
}

write_secret_if_missing() {
  local path="$1" value="$2"
  if [[ -e "$path" ]]; then
    [[ -f "$path" ]] || { echo "Internal secret path is not a regular file: $path" >&2; return 1; }
    [[ -s "$path" ]] || { echo "Internal secret file is empty: $path" >&2; return 1; }
    return
  fi
  printf '%s\n' "$value" > "$path"
}

production_secrets_ready() {
  local target_dir="$1" name expected metadata
  local names=(postgres_password database_url app_secret platform_admin_password monitoring_token)

  [[ -d "$target_dir" ]] || return 1
  metadata="$(stat -c '%u:%g:%a' "$target_dir" 2>/dev/null || true)"
  [[ "$metadata" == "10001:10001:755" ]] || return 1

  for name in "${names[@]}"; do
    [[ -f "$target_dir/$name" && -s "$target_dir/$name" ]] || return 1
    if [[ "$name" == "postgres_password" ]]; then
      expected="10001:10001:644"
    else
      expected="10001:10001:640"
    fi
    metadata="$(stat -c '%u:%g:%a' "$target_dir/$name" 2>/dev/null || true)"
    [[ "$metadata" == "$expected" ]] || return 1
  done
}

secure_internal_secret_permissions() {
  local environment="$1" target_dir="$2"
  chmod 0755 "$target_dir"

  if [[ "$environment" == "production" ]]; then
    if [[ "$(id -u)" == "0" ]]; then
      chown -R 10001:10001 "$target_dir"
    elif [[ "$(id -u)" != "10001" || "$(id -g)" != "10001" ]]; then
      echo "Production internal secrets must be initialized by root or runtime user 10001:10001." >&2
      return 1
    fi
    find "$target_dir" -maxdepth 1 -type f -exec chmod 0640 {} +
    # PostgreSQL runs under its image-specific UID and only needs this one value.
    chmod 0644 "$target_dir/postgres_password"
  else
    # Development containers use image-specific users as well. The directory is
    # local, ignored by Git and contains machine-local generated values only.
    find "$target_dir" -maxdepth 1 -type f -exec chmod 0644 {} +
  fi
}

ensure_internal_secrets() {
  local environment="$1" private_file="$2"
  local target_dir="$DOCKER_DIR/secrets/$environment"
  local postgres_password database_url expected_database_url value

  # Once the production secret set has been initialized securely, normal Docker
  # operators do not need permission to read or rewrite its contents. Docker
  # mounts the files directly for the runtime containers.
  if [[ "$environment" == "production" && "$(id -u)" != "0" && ( "$(id -u)" != "10001" || "$(id -g)" != "10001" ) ]]; then
    if production_secrets_ready "$target_dir"; then
      INTERNAL_SECRETS_DIR="$target_dir"
      export INTERNAL_SECRETS_DIR
      return 0
    fi
    echo "Production internal secrets are missing or do not have the expected secure ownership/permissions." >&2
    echo "Initialize or repair them once as root, then rerun this command as the normal deployment user." >&2
    return 1
  fi

  mkdir -p "$target_dir"

  if [[ -f "$target_dir/postgres_password" ]]; then
    postgres_password="$(tr -d '\r\n' < "$target_dir/postgres_password")"
  else
    postgres_password="$(legacy_value POSTGRES_PASSWORD "$private_file")"
    [[ -n "$postgres_password" ]] || postgres_password="$(random_hex 32)"
    write_secret_if_missing "$target_dir/postgres_password" "$postgres_password"
  fi

  expected_database_url="postgresql+asyncpg://zahlmeister:${postgres_password}@db:5432/zahlmeister"
  if [[ -f "$target_dir/database_url" ]]; then
    database_url="$(tr -d '\r\n' < "$target_dir/database_url")"
  else
    database_url="$(legacy_value DATABASE_URL "$private_file")"
    if [[ -n "$database_url" && "$database_url" != "$expected_database_url" ]]; then
      echo "Legacy DATABASE_URL does not match the standard Zahlmeister database connection." >&2
      echo "Refusing to rewrite database credentials automatically." >&2
      return 1
    fi
    [[ -n "$database_url" ]] || database_url="$expected_database_url"
    write_secret_if_missing "$target_dir/database_url" "$database_url"
  fi

  if [[ "$database_url" != "$expected_database_url" ]]; then
    echo "Internal database_url and postgres_password do not match." >&2
    echo "Fix docker/secrets/$environment before starting the stack." >&2
    return 1
  fi

  value="$(legacy_value APP_SECRET "$private_file")"
  [[ -n "$value" ]] || value="$(random_hex 48)"
  write_secret_if_missing "$target_dir/app_secret" "$value"

  value="$(legacy_value PLATFORM_ADMIN_BOOTSTRAP_PASSWORD "$private_file")"
  [[ -n "$value" ]] || value="$(random_hex 24)"
  write_secret_if_missing "$target_dir/platform_admin_password" "$value"

  value="$(legacy_value MONITORING_TOKEN "$private_file")"
  [[ -n "$value" ]] || value="$(random_hex 32)"
  write_secret_if_missing "$target_dir/monitoring_token" "$value"

  secure_internal_secret_permissions "$environment" "$target_dir"
  INTERNAL_SECRETS_DIR="$target_dir"
  export INTERNAL_SECRETS_DIR
}

# Internal runtime secrets are created once and then reused. Existing legacy
# .env values are adopted on first migration to preserve database/encryption state.
ensure_internal_secrets "$ENVIRONMENT" "$PRIVATE_ENV_FILE"
check_private_env_file

export ENVIRONMENT BASE_ENV_FILE PRIVATE_ENV_FILE COMPOSE_FILE INTERNAL_SECRETS_DIR

# Outside a deployment (restore, platform-admin access, the menu), production
# runs the images the last deployment recorded. compose.prod.yml would
# otherwise fall back to :latest tags, which exist only on a build machine.
# deploy-production.sh sets the images it deploys after loading this file.
if [[ "$ENVIRONMENT" == "production" && -z "${BACKEND_IMAGE:-}" \
  && -s "$DOCKER_DIR/.deployed-image-tag" && -s "$DOCKER_DIR/.deployed-image-registry" ]]; then
  deployed_tag="$(tr -d '\r\n' < "$DOCKER_DIR/.deployed-image-tag")"
  deployed_registry="$(tr -d '\r\n' < "$DOCKER_DIR/.deployed-image-registry")"
  export BACKEND_IMAGE="${deployed_registry%/}/zahlmeister-backend:${deployed_tag}"
  export FRONTEND_IMAGE="${deployed_registry%/}/zahlmeister-frontend:${deployed_tag}"
fi

# docker compose for the active environment, as every script and manage.sh use it.
compose() {
  docker compose "${COMPOSE_ENV_ARGS[@]}" -f "$COMPOSE_FILE" "$@"
}

# Waits until a service of the active stack is healthy, or running when it has
# no healthcheck. Fails when it turns unhealthy, exits or times out.
wait_service() {
  local service="$1" timeout="${2:-180}" started cid status
  started="$(date +%s)"
  while true; do
    cid="$(compose ps -q "$service" 2>/dev/null || true)"
    if [[ -n "$cid" ]]; then
      status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || true)"
      case "$status" in
        healthy|running)
          echo "[OK] $service: $status"
          return 0
          ;;
        unhealthy|exited|dead)
          echo "ERROR: $service became $status" >&2
          return 1
          ;;
      esac
    fi
    if (( $(date +%s) - started >= timeout )); then
      echo "ERROR: Timeout waiting for $service" >&2
      return 1
    fi
    sleep 2
  done
}

# Runs a shell snippet in the db container, authenticated with the mounted
# PostgreSQL password. Standard input is passed through (pg_restore reads it).
db_exec() {
  compose exec -T db sh -ec '
    if [ -n "${POSTGRES_PASSWORD_FILE:-}" ] && [ -f "$POSTGRES_PASSWORD_FILE" ]; then
      export PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")"
    else
      export PGPASSWORD="${POSTGRES_PASSWORD:-}"
    fi
    eval "$1"
  ' sh "$1"
}
