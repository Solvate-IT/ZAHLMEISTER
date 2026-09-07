#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

echo "== Containers =="
compose ps

echo
echo "== Backend readiness =="
compose exec -T backend python - <<'PY'
import urllib.request
try:
    with urllib.request.urlopen("http://127.0.0.1:8000/api/v1/ready", timeout=3) as response:
        print(response.read().decode())
except Exception as exc:
    print(f"NOT READY: {exc}")
PY

echo
echo "== Queue / worker =="
compose exec -T db sh -ec '
  if [ -n "${POSTGRES_PASSWORD_FILE:-}" ] && [ -f "$POSTGRES_PASSWORD_FILE" ]; then
    export PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")"
  else
    export PGPASSWORD="${POSTGRES_PASSWORD:-}"
  fi
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -P pager=off -c "
    SELECT status, count(*) FROM scheduled_jobs GROUP BY status ORDER BY status;
    SELECT name, last_seen_at, now() - last_seen_at AS age FROM runtime_heartbeats ORDER BY name;
  "
'
