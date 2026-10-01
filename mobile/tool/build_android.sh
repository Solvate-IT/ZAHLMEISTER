#!/usr/bin/env bash
# Builds the Android app inside the mobile build image (docker/mobile.Dockerfile).
# Run it through ./docker/manage.sh -> 11) Android App, not by hand.
#
#   build_android.sh <apk|aab> <debug|release>
#
# frontend/ and mobile/ are mounted read-only under /src. The build runs in a
# private copy under /work, next to the node_modules baked into the image, so it
# never touches the host's node_modules, .next or Gradle state. Only the
# finished artifact is written, as /out/<debug|release>/Zahlmeister.<apk|aab>
# (mobile/dist on the host).
set -euo pipefail

FORMAT="${1:-}"
VARIANT="${2:-}"
case "$FORMAT:$VARIANT" in
  apk:debug|apk:release|aab:debug|aab:release) ;;
  *) echo "Usage: $0 <apk|aab> <debug|release>" >&2; exit 2 ;;
esac

SRC=/src
WORK=/work
OUT=/out
API_BASE="${ZAHLMEISTER_API_BASE_URL:-}"

[[ -n "$API_BASE" ]] || { echo "ZAHLMEISTER_API_BASE_URL is required." >&2; exit 1; }
# The app runs on https://localhost; Android WebView blocks plain-HTTP API calls
# from it as mixed content.
[[ "$API_BASE" == https://* ]] || { echo "The API base must be an https:// URL: $API_BASE" >&2; exit 1; }
[[ -f "$SRC/mobile/android/app/build.gradle" ]] || {
  echo "mobile/android is missing. Generate it once with mobile/tool/bootstrap_mobile.sh and commit it." >&2
  exit 1
}
for dir in frontend mobile; do
  cmp -s "$SRC/$dir/package-lock.json" "$WORK/$dir/package-lock.json" || {
    echo "$dir/package-lock.json changed since the build image was made." >&2
    echo "Rebuild it: ./docker/manage.sh -> Android App -> 7) Rebuild Android build image." >&2
    exit 1
  }
done

echo "== Copying sources =="
tar -C "$SRC" -cf - \
  --exclude=frontend/node_modules --exclude=frontend/.next --exclude=frontend/out \
  --exclude=mobile/node_modules --exclude=mobile/dist \
  --exclude=mobile/android/.gradle --exclude=mobile/android/build --exclude=mobile/android/app/build \
  --exclude=mobile/android/local.properties --exclude=mobile/android/capacitor-cordova-android-plugins \
  frontend mobile | tar -C "$WORK" -xf -

echo "== Building the web app against $API_BASE =="
(cd "$WORK/frontend" && NEXT_PUBLIC_API_BASE_URL="$API_BASE" npm run build)

echo "== Synchronizing Capacitor =="
(cd "$WORK/mobile" && npx cap sync android)

# cap sync regenerates this module from the Capacitor template. Its flatDir
# repository only serves Cordova plugins that ship local .aar/.jar files; while
# there are none, dropping it removes AGP's "Using flatDir" warning.
cordova="$WORK/mobile/android/capacitor-cordova-android-plugins"
if [[ -z "$(find "$cordova/src/main/libs" "$cordova/libs" -type f 2>/dev/null)" ]]; then
  perl -0pi -e 's/\n[ \t]*flatDir[ \t]*\{[^}]*\}//' "$cordova/build.gradle"
fi

case "$FORMAT" in
  apk) task="assemble"; built="app/build/outputs/apk/$VARIANT/app-$VARIANT.apk" ;;
  aab) task="bundle"; built="app/build/outputs/bundle/$VARIANT/app-$VARIANT.aab" ;;
esac
task="$task${VARIANT^}"

# --warn: a successful build prints nothing but real warnings (the release
# signing banner included) instead of ~300 task lines.
echo "== Gradle $task (1-4 minutes) =="
(cd "$WORK/mobile/android" && ./gradlew --warn --console=plain --no-problems-report "$task")

version_name="$(node -p 'require(process.argv[1]).version' "$WORK/mobile/package.json")"
version_code="$(sed -nE 's/^[[:space:]]*versionCode[[:space:]]+([0-9]+).*/\1/p' "$WORK/mobile/android/app/build.gradle" | head -n 1)"
artifact="$OUT/$VARIANT/Zahlmeister.$FORMAT"
install -d "$OUT/$VARIANT"
install -m 0644 "$WORK/mobile/android/$built" "$artifact"

echo
echo "== Signature =="
if [[ "$FORMAT" == "apk" ]]; then
  signer="$(apksigner verify --print-certs "$artifact")"
else
  signer="$(keytool -printcert -jarfile "$artifact")"
fi
printf '%s\n' "$signer" | grep -E 'DN:|Owner:|SHA-256|SHA256:'

echo
echo "Built:   mobile/dist/$VARIANT/Zahlmeister.$FORMAT"
echo "Version: $version_name (versionCode $version_code)"
echo "API:     $API_BASE"
echo "SHA-256: $(sha256sum "$artifact" | cut -d' ' -f1)"
if [[ "$VARIANT" == "debug" ]]; then
  echo "Debuggable build: install it and open the WebView DevTools from Android App -> 5) Device."
  echo "Not accepted on Google Play testing or production tracks."
elif printf '%s\n' "$signer" | grep -q 'CN=Android Debug'; then
  echo
  echo "WARNING: signed with the DEBUG key because docker/secrets/android/key.properties is missing."
  echo "Google Play rejects this artifact. Create the upload keystore first (Android App -> 6)."
fi
