#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${ZM_ENV_FILE:-$DOCKER_DIR/.env}"
COMPOSE_FILE="${ZM_COMPOSE_FILE:-$DOCKER_DIR/compose.yml}"
BACKUP_DIR="${ZM_BACKUP_DIR:-$DOCKER_DIR/backups}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Environment file not found: $ENV_FILE" >&2
  exit 1
fi

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR" 2>/dev/null || true
umask 077
