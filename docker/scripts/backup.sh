#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
PREFIX="${ZM_BACKUP_PREFIX:-zahlmeister}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARGET="$BACKUP_DIR/${PREFIX}_${STAMP}.dump"
TMP="$TARGET.tmp"

cleanup() {
  rm -f "$TMP"
}
trap cleanup EXIT

compose exec -T db sh -ec '
  if [ -n "${POSTGRES_PASSWORD_FILE:-}" ] && [ -f "$POSTGRES_PASSWORD_FILE" ]; then
    export PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")"
  else
    export PGPASSWORD="${POSTGRES_PASSWORD:-}"
  fi
  exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-privileges
' > "$TMP"

[[ -s "$TMP" ]] || { echo "Backup is empty" >&2; exit 1; }
compose exec -T db pg_restore -l < "$TMP" >/dev/null
mv "$TMP" "$TARGET"
(cd "$BACKUP_DIR" && sha256sum "$(basename "$TARGET")" > "$(basename "$TARGET").sha256")

find "$BACKUP_DIR" -maxdepth 1 -type f \
  \( -name '*.dump' -o -name '*.dump.sha256' \) \
  -mtime "+$RETENTION_DAYS" -delete

echo "$TARGET"
