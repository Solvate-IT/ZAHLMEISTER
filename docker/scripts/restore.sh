#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

BACKUP_FILE="${1:-}"
FORCE="${2:-}"
if [[ -z "$BACKUP_FILE" || ! -f "$BACKUP_FILE" ]]; then
  echo "Usage: $0 <backup.dump> --force" >&2
  exit 2
fi
if [[ "$FORCE" != "--force" ]]; then
  echo "Restore is destructive. Re-run with --force." >&2
  exit 2
fi

if [[ -f "$BACKUP_FILE.sha256" ]]; then
  (cd "$(dirname "$BACKUP_FILE")" && sha256sum -c "$(basename "$BACKUP_FILE.sha256")")
fi
compose exec -T db pg_restore -l < "$BACKUP_FILE" >/dev/null

echo "Creating safety backup before restore..."
ZM_BACKUP_PREFIX=pre_restore "$(dirname "$0")/backup.sh" >/dev/null

echo "Stopping application services..."
compose stop backend worker frontend || true

restore_failed=1
trap 'if [[ $restore_failed -ne 0 ]]; then echo "Restore failed. Application services remain stopped; use the pre_restore backup if needed." >&2; fi' EXIT

compose exec -T db sh -ec '
  if [ -n "${POSTGRES_PASSWORD_FILE:-}" ] && [ -f "$POSTGRES_PASSWORD_FILE" ]; then
    export PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")"
  else
    export PGPASSWORD="${POSTGRES_PASSWORD:-}"
  fi
  psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
    -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '\''$POSTGRES_DB'\'' AND pid <> pg_backend_pid();" >/dev/null
  dropdb -U "$POSTGRES_USER" --if-exists --force "$POSTGRES_DB"
  createdb -U "$POSTGRES_USER" "$POSTGRES_DB"
'

compose exec -T db sh -ec '
  if [ -n "${POSTGRES_PASSWORD_FILE:-}" ] && [ -f "$POSTGRES_PASSWORD_FILE" ]; then
    export PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")"
  else
    export PGPASSWORD="${POSTGRES_PASSWORD:-}"
  fi
  exec pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges --exit-on-error
' < "$BACKUP_FILE"

# The bootstrap is idempotent and only creates schema objects that are absent.
# Running it after restore verifies that the restored database matches the current ORM model.
compose run --rm bootstrap
compose up -d backend worker frontend
restore_failed=0
trap - EXIT

echo "Restore completed: $BACKUP_FILE"
