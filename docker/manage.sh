#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DOCKER_DIR="$SCRIPT_DIR"
source "$SCRIPT_DIR/scripts/env.sh"

compose() {
  docker compose "${COMPOSE_ENV_ARGS[@]}" -f "$COMPOSE_FILE" "$@"
}

pause() { read -r -p "Press Enter to continue..." _; }

start_stack() {
  if [[ "$ENVIRONMENT" == "production" ]]; then
    compose start
  else
    compose up -d
  fi
}

stop_stack() {
  if [[ "$ENVIRONMENT" == "production" ]]; then
    compose stop
  else
    compose down
  fi
}

clean_build() {
  if [[ "$ENVIRONMENT" == "production" ]]; then
    echo "ERROR: Production images are built, tested and deployed only by the main-branch GitHub Action." >&2
    return 1
  fi
  compose down --remove-orphans
  compose build --no-cache
  compose up -d
}

# predeploy.sh names its containers and network ...-<its PID>; while that run
# is alive they belong to it, whoever started it.
predeploy_run_alive() {
  local pid="${1##*-}"
  [[ "$pid" =~ ^[0-9]+$ ]] && grep -qs predeploy.sh "/proc/$pid/cmdline"
}

# Option 5, as in the other Solvate projects (RCOD, LUHEOD, ...): removes what
# this project left behind, without touching the stack itself:
#   - containers of services no longer in compose.yml (what Clean Build's
#     --remove-orphans removes, but without taking the stack down),
#   - stopped `compose run` containers (a running one is a build, adb or shell
#     session in another terminal and is kept),
#   - containers and networks of interrupted pre-deployment checks (a check
#     that is still running keeps its own).
clean_orphans() {
  local project services id name service oneoff state
  local ids=() names=() networks=() kept=()
  echo "🧽 Cleaning up orphaned containers..."
  project="$(env_value COMPOSE_PROJECT_NAME zahlmeister)"
  # Without the service list every container would look orphaned.
  services="$(compose --profile '*' config --services)" && [[ -n "$services" ]] || {
    echo "❌ Could not read the services from compose.yml; nothing removed." >&2
    return 1
  }

  while IFS='|' read -r id name service oneoff state; do
    if [[ "$oneoff" == "True" && "$state" == "running" ]]; then
      kept+=("$name")
    elif [[ "$oneoff" == "True" ]] || ! grep -qxF -- "$service" <<<"$services"; then
      ids+=("$id")
      names+=("$name")
    fi
  done < <(docker ps -a --filter "label=com.docker.compose.project=${project}" \
    --format '{{.ID}}|{{.Names}}|{{.Label "com.docker.compose.service"}}|{{.Label "com.docker.compose.oneoff"}}|{{.State}}')

  while IFS='|' read -r id name; do
    if predeploy_run_alive "$name"; then
      kept+=("$name")
    else
      ids+=("$id")
      names+=("$name")
    fi
  done < <(docker ps -a --filter "name=^zahlmeister-predeploy-" --format '{{.ID}}|{{.Names}}')

  while IFS= read -r name; do
    predeploy_run_alive "$name" || networks+=("$name")
  done < <(docker network ls --filter "name=^zahlmeister-predeploy-" --format '{{.Name}}')

  if (( ${#ids[@]} )); then
    docker rm -f "${ids[@]}" >/dev/null || { echo "❌ Could not remove: ${names[*]}" >&2; return 1; }
    echo "✅ Removed orphan containers:"
    printf '%s\n' "${names[@]}"
  fi
  if (( ${#networks[@]} )); then
    docker network rm "${networks[@]}" >/dev/null || { echo "❌ Could not remove: ${networks[*]}" >&2; return 1; }
    echo "✅ Removed orphan networks:"
    printf '%s\n' "${networks[@]}"
  fi
  (( ${#ids[@]} + ${#networks[@]} )) || echo "ℹ️ No orphan containers found."
  (( ${#kept[@]} == 0 )) || echo "ℹ️ Kept, still in use: ${kept[*]}"
}

status_stack() { compose ps; }
show_logs() { compose logs -f --tail=200; }
predeploy() { ZM_PRIVATE_ENV_FILE="$PRIVATE_ENV_FILE" "$SCRIPT_DIR/scripts/test.sh" all; }
backend_shell() { compose exec backend bash; }
frontend_shell() { compose exec frontend sh; }

reload_environment() {
  [[ "$ENVIRONMENT" == "production" ]] || {
    echo "ERROR: Reload .env is a production operation." >&2
    return 1
  }

  "$SCRIPT_DIR/scripts/reload-production-env.sh"
}

health_check() {
  local failed=0
  local worker_cid

  echo "== Production health check =="

  if compose exec -T db pg_isready -U zahlmeister -d zahlmeister >/dev/null 2>&1; then
    echo "[OK] db"
  else
    echo "[FAIL] db" >&2
    failed=1
  fi

  if compose exec -T backend python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/ready', timeout=3)" >/dev/null 2>&1; then
    echo "[OK] backend /ready"
  else
    echo "[FAIL] backend /ready" >&2
    failed=1
  fi

  worker_cid="$(compose ps -q worker 2>/dev/null || true)"
  if [[ -n "$worker_cid" ]] && [[ "$(docker inspect --format '{{.State.Running}}' "$worker_cid" 2>/dev/null || true)" == "true" ]]; then
    echo "[OK] worker"
  else
    echo "[FAIL] worker" >&2
    failed=1
  fi

  if compose exec -T frontend wget -qO- http://127.0.0.1:8080/ >/dev/null 2>&1; then
    echo "[OK] frontend"
  else
    echo "[FAIL] frontend" >&2
    failed=1
  fi

  return "$failed"
}

run_tests() {
  if [[ "$ENVIRONMENT" == "production" ]]; then
    echo "ERROR: Tests are run from isolated test images, not inside the production stack." >&2
    return 1
  fi

  local backend_test_image="zahlmeister-backend-test:local"
  local frontend_test_image="zahlmeister-frontend-test:local"

  (
    cd "$PROJECT_DIR"
    echo "== Building backend test image =="
    docker build --target test -f "$SCRIPT_DIR/backend.Dockerfile" -t "$backend_test_image" .
    echo "== Running backend tests =="
    docker run --rm \
      -e ENVIRONMENT=test \
      -e READINESS_REQUIRE_WORKER=false \
      "$backend_test_image" \
      sh -c 'ruff check app tests && python -m pytest -q'

    echo "== Building frontend test image and running frontend tests =="
    docker build --target test -f "$SCRIPT_DIR/frontend.Dockerfile" -t "$frontend_test_image" .
  )

  "$SCRIPT_DIR/scripts/platform-admin-access.test.sh"
}

MOBILE_SIGNING_DIR="$SCRIPT_DIR/secrets/android"
MOBILE_IMAGE="zahlmeister-mobile-build:local"

# The Android toolchain is the compose service "mobile" (and "mobile-device"
# for the phone) behind the "tools" profile, built with the host uid/gid so
# artifacts stay host-owned.
mobile_compose() {
  HOST_UID="$(id -u)" HOST_GID="$(id -g)" compose --profile tools "$@"
}

# `compose run --rm` for the tools services. Compose 5.0.1 logs a spurious
# "No services to build" warning on every run, even for services without a
# build section; --log-level error drops it and --progress quiet the container
# create lines. A failing command still returns its exit status.
mobile_run() {
  HOST_UID="$(id -u)" HOST_GID="$(id -g)" docker --log-level error compose --progress quiet \
    "${COMPOSE_ENV_ARGS[@]}" -f "$COMPOSE_FILE" --profile tools run --rm "$@"
}

# With a terminal the container gets a TTY, so Ctrl-C reaches the build or adb
# inside it. Piped input gets -T and /dev/null instead: `compose run` forwards
# stdin even with -T and would swallow the menu input that follows.
mobile_run_attached() {
  if [[ -t 0 ]]; then
    mobile_run "$@"
  else
    mobile_run -T "$@" </dev/null
  fi
}

# The app is built for the production API unless MOBILE_API_BASE_URL is set.
mobile_api_base() {
  local app_url
  app_url="$(read_env_value_from_file "$PROD_ENV_FILE" PUBLIC_APP_URL)"
  printf '%s' "${MOBILE_API_BASE_URL:-${app_url%/}/api/v1}"
}

mobile_version() {
  local name code
  name="$(sed -nE 's/^[[:space:]]*"version":[[:space:]]*"([^"]+)".*/\1/p' "$PROJECT_DIR/mobile/package.json" | head -n 1)"
  code="$(sed -nE 's/^[[:space:]]*versionCode[[:space:]]+([0-9]+).*/\1/p' "$PROJECT_DIR/mobile/android/app/build.gradle" 2>/dev/null | head -n 1)"
  printf '%s (versionCode %s)' "${name:-?}" "${code:-?}"
}

# Created here rather than by Docker, which would make the bind-mount sources root-owned.
prepare_mobile_dirs() {
  mkdir -p "$PROJECT_DIR/mobile/dist" "$MOBILE_SIGNING_DIR"
  chmod 700 "$MOBILE_SIGNING_DIR"
}

# Before every build: a cache hit unless a lockfile or the Dockerfile changed,
# so it stays quiet once the image exists.
build_mobile_image() {
  if [[ "${1:-}" != "--no-cache" ]] && docker image inspect "$MOBILE_IMAGE" >/dev/null 2>&1; then
    echo "== Checking the Android build image =="
    mobile_compose build --quiet mobile
  else
    echo "== Building the Android build image (the first build downloads about 1 GB) =="
    mobile_compose build "$@" mobile
  fi
}

build_android() {
  local format="$1" variant="$2"
  prepare_mobile_dirs
  build_mobile_image
  mobile_run_attached -e ZAHLMEISTER_API_BASE_URL="$(mobile_api_base)" mobile \
    bash /src/mobile/tool/build_android.sh "$format" "$variant"
}

create_upload_keystore() {
  local password confirm escaped
  prepare_mobile_dirs
  if [[ -e "$MOBILE_SIGNING_DIR/upload-keystore.jks" || -e "$MOBILE_SIGNING_DIR/key.properties" ]]; then
    echo "An upload key already exists in docker/secrets/android/ and is never overwritten:" >&2
    echo "it is the only key that can sign updates of the published app." >&2
    return 1
  fi

  read -r -s -p "New keystore password (at least 6 characters): " password; echo
  read -r -s -p "Repeat the password: " confirm; echo
  [[ "$password" == "$confirm" ]] || { echo "The passwords differ." >&2; return 1; }
  (( ${#password} >= 6 )) || { echo "The password is too short." >&2; return 1; }
  # key.properties would lose leading blanks, so keytool and Gradle would disagree.
  [[ "$password" != [[:space:]]* && "$password" != *[[:space:]] ]] || {
    echo "The password must not start or end with a space." >&2
    return 1
  }
  # keytool refuses non-ASCII passwords for PKCS12 keystores.
  (LC_ALL=C; [[ "$password" != *[![:print:]]* ]]) || {
    echo "The password may contain only ASCII letters, digits, spaces and symbols." >&2
    return 1
  }

  build_mobile_image || return 1
  # The password reaches keytool through the environment, never the command line.
  ZM_KEYSTORE_PASSWORD="$password" mobile_run -T -e ZM_KEYSTORE_PASSWORD \
    -v "$MOBILE_SIGNING_DIR:/keys" mobile bash -c '
      keytool -genkeypair -keystore /keys/upload-keystore.jks -storetype PKCS12 \
        -alias upload -keyalg RSA -keysize 4096 -validity 10000 \
        -dname "CN=Zahlmeister, OU=Mobile, O=Solvate IT, L=Graz, ST=Styria, C=AT" \
        -storepass:env ZM_KEYSTORE_PASSWORD -keypass:env ZM_KEYSTORE_PASSWORD &&
      keytool -list -v -keystore /keys/upload-keystore.jks -storepass:env ZM_KEYSTORE_PASSWORD |
        grep -E "Owner:|Valid from|SHA1:|SHA256:"
    ' </dev/null || return 1

  chmod 600 "$MOBILE_SIGNING_DIR/upload-keystore.jks"
  escaped="${password//\\/\\\\}"
  (
    umask 077
    printf 'storeFile=upload-keystore.jks\nstorePassword=%s\nkeyAlias=upload\nkeyPassword=%s\n' \
      "$escaped" "$escaped" > "$MOBILE_SIGNING_DIR/key.properties"
  )
  echo "Upload key created in docker/secrets/android/."
  echo "Back up upload-keystore.jks and its password outside this computer now."
}

# One mobile/tool/android_device.sh action in the mobile-device container.
device_run() {
  local env_args=()
  # Only one adb server can own the phone's USB connection. The container's
  # server runs as root, so a server owned by this user is a host one.
  if pgrep -u "$(id -u)" -x adb >/dev/null 2>&1; then
    echo "An adb server is running on this computer and holds the phone's USB connection." >&2
    echo "Stop it first (adb kill-server; close Android Studio's device manager), then retry." >&2
    return 1
  fi
  docker image inspect "$MOBILE_IMAGE" >/dev/null 2>&1 || build_mobile_image || return 1
  [[ -z "${ANDROID_SERIAL:-}" ]] || env_args=(-e ANDROID_SERIAL)
  mobile_run_attached "${env_args[@]}" mobile-device bash /tool/android_device.sh "$@"
}

# Lets the user pick a build from mobile/dist, newest first.
install_build() {
  local builds=() build choice i=0
  mapfile -t builds < <(ls -t "$PROJECT_DIR"/mobile/dist/{debug,release}/Zahlmeister.{apk,aab} 2>/dev/null)
  (( ${#builds[@]} )) || { echo "No build in mobile/dist/ yet. Build one first (Android App -> 1 to 4)." >&2; return 1; }

  echo "Builds in mobile/dist (newest first):"
  for build in "${builds[@]}"; do
    i=$((i + 1))
    printf '  %d) %-22s %s\n' "$i" "${build#"$PROJECT_DIR"/mobile/dist/}" "$(date -r "$build" '+%Y-%m-%d %H:%M')"
  done
  read -r -p "Install which build [1]: " choice
  choice="${choice:-1}"
  [[ "$choice" =~ ^[0-9]+$ ]] && choice=$((10#$choice)) && (( choice >= 1 && choice <= ${#builds[@]} )) || {
    echo "Invalid selection" >&2
    return 1
  }
  device_run install "/dist/${builds[choice - 1]#"$PROJECT_DIR"/mobile/dist/}"
}

device_menu() {
  local choice
  while true; do
    cat <<EOF
------------------------------------------------------------
 Zahlmeister - Android device (USB)
------------------------------------------------------------
 1) Show connected devices
 2) Install a build from mobile/dist (APK or AAB)
 3) Start app
 4) Stop app
 5) App log (Ctrl-C to stop)
 6) WebView DevTools in Chrome (debug builds; Ctrl-C to stop)
 7) Clear app data
 8) Uninstall app
 9) adb shell
 b) Back
------------------------------------------------------------
 Phone: Developer options -> USB debugging on, connected by USB.
 Several phones: start manage.sh with ANDROID_SERIAL=<serial>.
EOF
    read -r -p "Select: " choice

    case "$choice" in
      1) device_run devices || true; pause ;;
      2) install_build || echo "Install failed." >&2; pause ;;
      3) device_run start || true; pause ;;
      4) device_run stop || true; pause ;;
      5) device_run logs || true; pause ;;
      6) device_run devtools || true; pause ;;
      7) device_run clear || true; pause ;;
      8) device_run uninstall || true; pause ;;
      9) device_run shell || true ;;
      b|B) return 0 ;;
      *) echo "Invalid selection"; pause ;;
    esac
  done
}

android_menu() {
  local choice signing
  while true; do
    if [[ -f "$MOBILE_SIGNING_DIR/key.properties" ]]; then
      signing="docker/secrets/android/key.properties"
    else
      signing="none - release builds get the debug key (6 creates one)"
    fi

    cat <<EOF
------------------------------------------------------------
 Zahlmeister - Android app
------------------------------------------------------------
 1) Debug APK    - debuggable; install and debug with 5
 2) Debug AAB    - debuggable bundle; internal app sharing
 3) Release APK  - upload-key signed; direct install and testers
 4) Release AAB  - upload-key signed; Google Play upload
 5) Device       - install, start, stop, log, DevTools (USB)
 6) Create upload keystore
 7) Rebuild Android build image
 b) Back
------------------------------------------------------------
 Version: $(mobile_version)
 API:     $(mobile_api_base)
 Signing: ${signing}
 Output:  mobile/dist/debug|release/Zahlmeister.apk|aab
EOF
    read -r -p "Select: " choice

    case "$choice" in
      1) build_android apk debug; pause ;;
      2) build_android aab debug; pause ;;
      3) build_android apk release; pause ;;
      4) build_android aab release; pause ;;
      5) device_menu ;;
      6) if ! create_upload_keystore; then echo "No keystore created." >&2; fi; pause ;;
      7) build_mobile_image --no-cache; pause ;;
      b|B) return 0 ;;
      *) echo "Invalid selection"; pause ;;
    esac
  done
}

production_menu() {
  local frontend_url choice
  frontend_url="$(env_value PUBLIC_APP_URL "https://zahlmeister.solvate.at")"

  cat <<EOF
------------------------------------------------------------
 Zahlmeister - Docker production
------------------------------------------------------------
 1) Start Stack
 2) Stop Stack
 3) Status
 4) Logs
 5) Reload .env / Recreate App Services
 6) Health Check
 7) Backend Shell
 8) Frontend Shell
 q) Quit
------------------------------------------------------------
 Frontend: ${frontend_url}
EOF
  read -r -p "Select: " choice

  case "$choice" in
    1) start_stack ;;
    2) stop_stack ;;
    3) status_stack; pause ;;
    4) show_logs ;;
    5) if ! reload_environment; then echo "Reload failed." >&2; fi; pause ;;
    6) if ! health_check; then echo "Health check failed." >&2; fi; pause ;;
    7) backend_shell ;;
    8) frontend_shell ;;
    q|Q) exit 0 ;;
    *) echo "Invalid selection"; pause ;;
  esac
}

development_menu() {
  local frontend_port frontend_url mailpit_port project choice
  frontend_port="$(env_value FRONTEND_PORT 3003)"
  frontend_url="$(env_value PUBLIC_APP_URL "http://localhost:${frontend_port}")"
  mailpit_port="$(env_value MAILPIT_PORT 8028)"
  project="$(env_value COMPOSE_PROJECT_NAME zahlmeister)"

  cat <<EOF
------------------------------------------------------------
 Zahlmeister - Docker development
------------------------------------------------------------
 1) Start
 2) Stop
 3) Clean Build
 4) Status
 5) Clean Orphan Containers (${project})
 6) Logs
 7) Pre-Deployment Checks
 8) Backend Shell
 9) Frontend Shell
10) Tests
11) Android App (APK / AAB)
 q) Quit
------------------------------------------------------------
 Frontend: ${frontend_url}
 Backend:  /api/v1/health and /api/v1/ready
 Mailpit:  http://localhost:${mailpit_port}
EOF
  read -r -p "Select: " choice

  case "$choice" in
    1) start_stack ;;
    2) stop_stack ;;
    3) clean_build ;;
    4) status_stack; pause ;;
    5) clean_orphans || true; pause ;;
    6) show_logs ;;
    7) predeploy; pause ;;
    8) backend_shell ;;
    9) frontend_shell ;;
    10) run_tests; pause ;;
    11) android_menu ;;
    q|Q) exit 0 ;;
    *) echo "Invalid selection"; pause ;;
  esac
}

while true; do
  if [[ "$ENVIRONMENT" == "production" ]]; then
    production_menu
  else
    development_menu
  fi
done
