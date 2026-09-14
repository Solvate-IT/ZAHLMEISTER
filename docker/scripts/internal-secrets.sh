#!/usr/bin/env bash

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
