#!/usr/bin/env bash
# Controls the Zahlmeister app on a USB-connected Android phone from the
# mobile-device container (docker/compose.yml). Use ./docker/manage.sh ->
# 11) Android App -> 5) Device rather than calling it directly.
#
#   android_device.sh devices | install <file in /dist> | start | stop | logs |
#                     devtools | clear | uninstall | shell
#
# Every call starts its own adb server, which ends with the container. Set
# ANDROID_SERIAL when more than one phone is connected. Long-running adb
# commands are not exec'd: they stay children of this script under the
# container's init, so Ctrl-C on the terminal ends them.
set -euo pipefail

APP_ID="at.solvate.zahlmeister"
ACTIVITY="$APP_ID/.MainActivity"
DEVTOOLS_PORT=9222
ACTION="${1:-}"

adb start-server >/dev/null 2>&1

# A fresh adb server needs a moment to enumerate USB devices, and a phone that
# does not trust this computer's key yet stays "unauthorized" until the prompt
# on its screen is accepted. The key lives in a volume, so that happens once.
wait_for_device() {
  local state asked=0 i
  for i in $(seq 1 60); do
    state="$(adb get-state 2>&1 || true)"
    case "$state" in
      device) return 0 ;;
      *unauthorized*)
        (( asked )) || echo "Accept \"Allow USB debugging?\" on the phone and tick \"Always allow from this computer\"."
        asked=1 ;;
      *"more than one"*)
        adb devices -l
        echo "Several devices are connected. Choose one: ANDROID_SERIAL=<serial> ./docker/manage.sh" >&2
        return 1 ;;
      *permission*)
        echo "No permission to open the phone's USB device: $state" >&2
        return 1 ;;
      *)
        if (( i >= 5 && ! asked )); then
          echo "No phone found. On the phone: Settings -> About phone -> tap \"Build number\" seven times," >&2
          echo "then Settings -> Developer options -> USB debugging. Connect it by USB and try again." >&2
          return 1
        fi ;;
    esac
    sleep 1
  done
  echo "Timed out waiting for the phone to accept this computer." >&2
  return 1
}

require_installed() {
  adb shell pm path "$APP_ID" 2>/dev/null | grep -q '^package:' || {
    echo "Zahlmeister is not installed on the phone. Install a build first (2)." >&2
    return 1
  }
}

app_pid() {
  adb shell pidof -s "$APP_ID" 2>/dev/null | tr -d '\r' || true
}

# The running app's pid, starting the app when it is not running.
running_pid() {
  local pid i
  pid="$(app_pid)"
  if [[ -z "$pid" ]]; then
    adb shell am start -n "$ACTIVITY" >/dev/null
    for i in $(seq 1 20); do
      pid="$(app_pid)"
      [[ -z "$pid" ]] || break
      sleep 0.5
    done
  fi
  [[ -n "$pid" ]] || { echo "Zahlmeister did not start." >&2; return 1; }
  printf '%s' "$pid"
}

# bundletool signs the APKs it cuts from an AAB. A release bundle gets the
# upload key when one exists, like the Gradle release build; everything else
# gets the debug key from ~/.android/debug.keystore, bundletool's default.
bundletool_signing_args() {
  local file="$1" props="${ZAHLMEISTER_SIGNING_DIR:-/run/secrets/android}/key.properties"
  [[ "$file" == */release/* && -f "$props" ]] || return 0
  install -d -m 700 /tmp/signing
  python3 - "$props" /tmp/signing <<'PY'
import re
import sys
from pathlib import Path

props, out = Path(sys.argv[1]), Path(sys.argv[2])
escapes = {"t": "\t", "n": "\n", "r": "\r", "f": "\f"}

def unescape(value):
    def repl(match):
        text = match.group(1)
        if text.startswith("u") and len(text) == 5:
            return chr(int(text[1:], 16))
        return escapes.get(text, text)
    return re.sub(r"\\(u[0-9a-fA-F]{4}|.)", repl, value)

# java.util.Properties rules: the key ends at the first unescaped '=', ':' or
# whitespace; leading whitespace of the value is dropped, trailing is kept.
values = {}
for raw in props.read_text(encoding="utf-8").splitlines():
    line = raw.lstrip()
    if not line or line[0] in "#!":
        continue
    match = re.match(r"((?:\\.|[^=:\s\\])*)\s*[=:\s]?\s*(.*)$", line)
    values[unescape(match.group(1))] = unescape(match.group(2))

for name in ("storeFile", "keyAlias"):
    (out / name).write_text(values[name], encoding="utf-8")
for name in ("storePassword", "keyPassword"):
    (out / name).write_text(values[name], encoding="utf-8")
    (out / name).chmod(0o600)
PY
  printf '%s\n' \
    "--ks=$(dirname "$props")/$(cat /tmp/signing/storeFile)" \
    "--ks-key-alias=$(cat /tmp/signing/keyAlias)" \
    "--ks-pass=file:/tmp/signing/storePassword" \
    "--key-pass=file:/tmp/signing/keyPassword"
}

install_build() {
  local file="$1" device_args=() sign_args=()
  [[ -f "$file" ]] || { echo "Build not found: $file" >&2; return 1; }
  wait_for_device
  [[ -z "${ANDROID_SERIAL:-}" ]] || device_args=(--device-id="$ANDROID_SERIAL")
  echo "Installing ${file#/dist/}..."
  case "$file" in
    *.apk)
      adb install -r "$file" || {
        echo "A build signed with another key (Play Store, other computer) must be uninstalled first (8)." >&2
        return 1
      } ;;
    *.aab)
      bundletool_signing_args "$file" > /tmp/signing.args
      mapfile -t sign_args < /tmp/signing.args
      # The split APKs Google Play would deliver to exactly this phone.
      bundletool build-apks --bundle="$file" --output=/tmp/Zahlmeister.apks --overwrite \
        --connected-device --adb="$(command -v adb)" "${device_args[@]}" "${sign_args[@]}"
      bundletool install-apks --apks=/tmp/Zahlmeister.apks --adb="$(command -v adb)" "${device_args[@]}" || {
        echo "A build signed with another key (Play Store, other computer) must be uninstalled first (8)." >&2
        return 1
      } ;;
    *) echo "Not an APK or AAB: $file" >&2; return 1 ;;
  esac
  echo "Installed. Start it with 3."
}

devtools() {
  local pid socket i
  wait_for_device
  require_installed
  pid="$(running_pid)"
  # A debuggable WebView opens @webview_devtools_remote_<pid> once it loads.
  for i in $(seq 1 20); do
    socket="$(adb shell cat /proc/net/unix 2>/dev/null | grep -aow "webview_devtools_remote_${pid}" | head -n 1 || true)"
    [[ -z "$socket" ]] || break
    sleep 0.5
  done
  [[ -n "$socket" ]] || {
    echo "The app exposes no WebView DevTools. Only debug builds do: install debug/Zahlmeister.apk." >&2
    return 1
  }
  adb forward "tcp:$DEVTOOLS_PORT" "localabstract:$socket" >/dev/null
  echo "WebView DevTools for Zahlmeister (pid $pid):"
  echo "  In Chrome on this computer open chrome://inspect/#devices and click \"inspect\" under Zahlmeister."
  echo "  (It is listed under the phone, or as a remote target on localhost:$DEVTOOLS_PORT.)"
  echo "The app log follows. Ctrl-C ends the session."
  adb logcat -v time --pid="$pid"
}

case "$ACTION" in
  devices)
    wait_for_device >/dev/null 2>&1 || true
    adb devices -l ;;
  install)
    install_build "${2:?install needs a file}" ;;
  start)
    wait_for_device
    require_installed
    adb shell am start -n "$ACTIVITY" >/dev/null
    echo "Zahlmeister started." ;;
  stop)
    wait_for_device
    require_installed
    adb shell am force-stop "$APP_ID"
    echo "Zahlmeister stopped." ;;
  logs)
    wait_for_device
    require_installed
    pid="$(running_pid)"
    echo "Log of Zahlmeister (pid $pid). Ctrl-C to stop."
    adb logcat -v time --pid="$pid" ;;
  devtools)
    devtools ;;
  clear)
    wait_for_device
    require_installed
    adb shell pm clear "$APP_ID" >/dev/null
    echo "App data cleared: the next start is a fresh installation (logged out)." ;;
  uninstall)
    wait_for_device
    require_installed
    adb uninstall "$APP_ID" >/dev/null
    echo "Zahlmeister uninstalled." ;;
  shell)
    wait_for_device
    adb shell ;;
  *)
    echo "Usage: $0 devices|install <file>|start|stop|logs|devtools|clear|uninstall|shell" >&2
    exit 2 ;;
esac
