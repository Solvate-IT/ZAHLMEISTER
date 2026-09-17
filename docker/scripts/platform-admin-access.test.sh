#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ADMIN_SCRIPT="$SCRIPT_DIR/platform-admin-access.sh"
MANAGE_SCRIPT="$DOCKER_DIR/manage.sh"

! grep -q 'Platform Admin Access' "$MANAGE_SCRIPT"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/scripts" "$TMP/bin"
cp "$ADMIN_SCRIPT" "$TMP/scripts/platform-admin-access.sh"

cat > "$TMP/scripts/env.sh" <<'ENV'
ENVIRONMENT="${TEST_ENVIRONMENT:-development}"
BASE_ENV_FILE="$PWD/.env.${ENVIRONMENT}"
COMPOSE_FILE="$PWD/compose.yml"
COMPOSE_ENV_ARGS=(--env-file "$BASE_ENV_FILE")
env_value() {
  case "$1" in
    PLATFORM_ADMIN_EMAILS) printf '%s' "${TEST_CONFIGURED_ADMINS}" ;;
    *) printf '%s' "${2:-}" ;;
  esac
}
ENV

cat > "$TMP/bin/docker" <<'DOCKER'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${TEST_DOCKER_LOG}"
if [[ "$*" == *"exec -T backend python -c"* ]]; then
  if [[ -f "${TEST_RECREATED_FILE}" ]]; then
    printf '%s\n' "${TEST_CONFIGURED_ADMINS}" | tr ',' '\n' | tr '[:upper:]' '[:lower:]'
  elif [[ "${TEST_RUNTIME_AVAILABLE:-1}" == "1" ]]; then
    printf '%s\n' "${TEST_RUNTIME_ADMINS}" | tr ',' '\n' | tr '[:upper:]' '[:lower:]'
  else
    exit 1
  fi
  exit 0
fi
if [[ "$*" == *"up -d --force-recreate backend worker"* ]]; then
  : > "${TEST_RECREATED_FILE}"
  exit 0
fi
if [[ "$*" == *"up -d backend worker"* ]]; then
  : > "${TEST_RECREATED_FILE}"
  exit 0
fi
if [[ "$*" == *"exec -e ZM_PLATFORM_ADMIN_EMAIL="*" backend python -c"* ]]; then
  exit 0
fi
exit 0
DOCKER
chmod +x "$TMP/bin/docker"

run_case() {
  local environment="$1" configured="$2" runtime="$3" input="$4" log="$5" recreated="$6"
  rm -f "$log" "$recreated"
  TEST_ENVIRONMENT="$environment" \
  TEST_CONFIGURED_ADMINS="$configured" \
  TEST_RUNTIME_ADMINS="$runtime" \
  TEST_DOCKER_LOG="$log" \
  TEST_RECREATED_FILE="$recreated" \
  PATH="$TMP/bin:$PATH" \
  bash "$TMP/scripts/platform-admin-access.sh" <<<"$input"
}

log1="$TMP/dev.log"; recreated1="$TMP/dev.recreated"
run_case development administration@zahlmeister.at administration@zahlmeister.at "" "$log1" "$recreated1" >/dev/null
! grep -q -- '--force-recreate backend worker' "$log1"
grep -q 'ZM_PLATFORM_ADMIN_EMAIL=administration@zahlmeister.at' "$log1"

log2="$TMP/prod.log"; recreated2="$TMP/prod.recreated"
run_case production Support@Solvate.at administration@zahlmeister.at $'\n\n' "$log2" "$recreated2" >/dev/null
[[ -f "$recreated2" ]]
grep -q -- '--force-recreate backend worker' "$log2"
grep -q 'ZM_PLATFORM_ADMIN_EMAIL=support@solvate.at' "$log2"
