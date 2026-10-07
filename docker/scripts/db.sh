#!/usr/bin/env bash
# PostgreSQL backup and restore for the environment selected in docker/.env.
#
#   db.sh backup                  verified dump in backups/ (prints its path)
#   db.sh restore <dump> --force  replaces the database with a dump
#
# deploy-production.sh takes a backup before every deployment.
set -euo pipefail

DOCKER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$DOCKER_DIR/scripts/env.sh"

BACKUP_DIR="${ZM_BACKUP_DIR:-$DOCKER_DIR/backups}"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR" 2>/dev/null || true
umask 077

backup() {
  local retention_days="${BACKUP_RETENTION_DAYS:-30}"
  local prefix="${ZM_BACKUP_PREFIX:-zahlmeister}"
  local target="$BACKUP_DIR/${prefix}_$(date -u +%Y%m%dT%H%M%SZ).dump"
  # Global: the EXIT trap runs after this function has returned.
  backup_tmp="$target.tmp"
  trap 'rm -f "$backup_tmp"' EXIT

  db_exec 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-privileges' > "$backup_tmp"

  [[ -s "$backup_tmp" ]] || { echo "Backup is empty" >&2; exit 1; }
  compose exec -T db pg_restore -l < "$backup_tmp" >/dev/null
  mv "$backup_tmp" "$target"
  (cd "$BACKUP_DIR" && sha256sum "$(basename "$target")" > "$(basename "$target").sha256")

  find "$BACKUP_DIR" -maxdepth 1 -type f \
    \( -name '*.dump' -o -name '*.dump.sha256' \) \
    -mtime "+$retention_days" -delete

  echo "$target"
}

restore() {
  local backup_file="${1:-}" force="${2:-}"
  if [[ -z "$backup_file" || ! -f "$backup_file" ]]; then
    echo "Usage: $0 restore <backup.dump> --force" >&2
    exit 2
  fi
  if [[ "$force" != "--force" ]]; then
    echo "Restore is destructive. Re-run with --force." >&2
    exit 2
  fi

  if [[ -f "$backup_file.sha256" ]]; then
    (cd "$(dirname "$backup_file")" && sha256sum -c "$(basename "$backup_file.sha256")")
  fi
  compose exec -T db pg_restore -l < "$backup_file" >/dev/null

  echo "Creating safety backup before restore..."
  ZM_BACKUP_PREFIX=pre_restore backup >/dev/null

  echo "Stopping application services..."
  compose stop backend worker frontend || true

  # Global, like backup_tmp: read by the EXIT trap.
  restore_failed=1
  trap 'if [[ $restore_failed -ne 0 ]]; then echo "Restore failed. Application services remain stopped; use the pre_restore backup if needed." >&2; fi' EXIT

  db_exec '
    psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
      -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '\''$POSTGRES_DB'\'' AND pid <> pg_backend_pid();" >/dev/null
    dropdb -U "$POSTGRES_USER" --if-exists --force "$POSTGRES_DB"
    createdb -U "$POSTGRES_USER" "$POSTGRES_DB"
  '

  db_exec 'exec pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges --exit-on-error' < "$backup_file"

  # The bootstrap is idempotent and only creates schema objects that are absent.
  # Running it after restore verifies that the restored database matches the current ORM model.
  compose run --rm bootstrap
  compose up -d backend worker frontend
  restore_failed=0
  trap - EXIT

  echo "Restore completed: $backup_file"
}

case "${1:-}" in
  backup) backup ;;
  restore) shift; restore "$@" ;;
  *)
    echo "Usage: $0 backup | restore <backup.dump> --force" >&2
    exit 2
    ;;
esac
