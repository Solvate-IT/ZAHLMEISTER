#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLUGIN="@capgo/native-purchases@8.7.0"

command -v node >/dev/null || { echo "Node.js is required." >&2; exit 1; }
command -v npm >/dev/null || { echo "npm is required." >&2; exit 1; }
[[ -f "$ROOT_DIR/package.json" ]] || { echo "mobile/package.json not found." >&2; exit 1; }
[[ -d "$ROOT_DIR/android" ]] || {
  echo "Android project not found. Run mobile/tool/bootstrap_mobile.sh first." >&2
  exit 1
}

cd "$ROOT_DIR"

echo "Installing Google Play Billing bridge: $PLUGIN"
npm install --save-exact "$PLUGIN"

# postinstall already hardens the reviewed plugin; run the guard explicitly as
# well so this preparation command remains safe even if npm lifecycle scripts
# were disabled for the install.
bash ./tool/harden_native_purchases.sh

# Capacitor discovers the plugin from package metadata and wires the native
# Android implementation into the generated project. The pinned plugin uses
# Google Play Billing Library 9.1.x and exposes purchase, restore and subscription
# management operations consumed by frontend/src/lib/googlePlayPurchases.ts.
npx cap sync android
npx cap doctor

echo "Google Play Billing bridge prepared."
echo "Review and commit mobile/package.json and mobile/package-lock.json before release."
echo "Then complete the Play Console and backend service-account steps in mobile/PLAY_STORE.md."
