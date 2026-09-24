#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT_DIR="$(cd "$ROOT_DIR/.." && pwd)"
FRONTEND_DIR="$PROJECT_DIR/frontend"
APP_HOST="${1:-${ZAHLMEISTER_APP_HOST:-app.example.com}}"
API_BASE="${2:-${ZAHLMEISTER_API_BASE_URL:-https://${APP_HOST}/api/v1}}"

command -v node >/dev/null || { echo "Node.js is required." >&2; exit 1; }
command -v npm >/dev/null || { echo "npm is required." >&2; exit 1; }
[[ -f "$FRONTEND_DIR/package.json" ]] || { echo "Frontend not found at $FRONTEND_DIR" >&2; exit 1; }

cd "$FRONTEND_DIR"
if [[ -f package-lock.json ]]; then npm ci; else npm install; fi
NEXT_PUBLIC_API_BASE_URL="$API_BASE" npm run check

cd "$ROOT_DIR"
if [[ -f package-lock.json ]]; then npm ci; else npm install; fi
[[ -d android ]] || npx cap add android
if [[ "$(uname -s)" == "Darwin" ]]; then
  [[ -d ios ]] || npx cap add ios
fi
npx cap sync android
if [[ -d ios ]]; then npx cap sync ios; fi

python3 - "$ROOT_DIR" "$APP_HOST" <<'PY'
import plistlib
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

root = Path(sys.argv[1])
host = sys.argv[2]
android_ns = "http://schemas.android.com/apk/res/android"
ET.register_namespace("android", android_ns)

def a(name: str) -> str:
    return f"{{{android_ns}}}{name}"

manifest = root / "android/app/src/main/AndroidManifest.xml"
if manifest.exists():
    tree = ET.parse(manifest)
    top = tree.getroot()
    app = top.find("application")
    if app is not None:
        app.set(a("label"), "Zahlmeister")
        activity = app.find("activity")
        if activity is not None:
            for node in list(activity.findall("intent-filter")):
                datas = node.findall("data")
                if any(d.get(a("host")) == host or d.get(a("scheme")) == "zahlmeister" for d in datas):
                    activity.remove(node)
            verified = ET.SubElement(activity, "intent-filter", {a("autoVerify"): "true"})
            ET.SubElement(verified, "action", {a("name"): "android.intent.action.VIEW"})
            ET.SubElement(verified, "category", {a("name"): "android.intent.category.DEFAULT"})
            ET.SubElement(verified, "category", {a("name"): "android.intent.category.BROWSABLE"})
            ET.SubElement(verified, "data", {a("scheme"): "https", a("host"): host})
            custom = ET.SubElement(activity, "intent-filter")
            ET.SubElement(custom, "action", {a("name"): "android.intent.action.VIEW"})
            ET.SubElement(custom, "category", {a("name"): "android.intent.category.DEFAULT"})
            ET.SubElement(custom, "category", {a("name"): "android.intent.category.BROWSABLE"})
            ET.SubElement(custom, "data", {a("scheme"): "zahlmeister"})
    tree.write(manifest, encoding="utf-8", xml_declaration=True)

plist_path = root / "ios/App/App/Info.plist"
if plist_path.exists():
    with plist_path.open("rb") as handle:
        plist = plistlib.load(handle)
    plist["CFBundleDisplayName"] = "Zahlmeister"
    plist["CFBundleName"] = "Zahlmeister"
    plist["CFBundleURLTypes"] = [{
        "CFBundleURLName": "at.solvate.zahlmeister",
        "CFBundleURLSchemes": ["zahlmeister"],
    }]
    with plist_path.open("wb") as handle:
        plistlib.dump(plist, handle, sort_keys=False)

entitlements = root / "ios/App/App/App.entitlements"
if plist_path.exists():
    entitlements.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>\n'
        '<key>com.apple.developer.associated-domains</key><array>\n'
        f'<string>applinks:{host}</string>\n'
        '</array></dict></plist>\n'
    )
    project = root / "ios/App/App.xcodeproj/project.pbxproj"
    if project.exists():
        text = project.read_text()
        marker = "CODE_SIGN_ENTITLEMENTS = App/App.entitlements;"
        if marker not in text:
            text = text.replace(
                "CODE_SIGN_STYLE = Automatic;",
                "CODE_SIGN_ENTITLEMENTS = App/App.entitlements;\n\t\t\t\tCODE_SIGN_STYLE = Automatic;",
            )
            project.write_text(text)
PY

# Generate native launcher icons directly from assets/logo.svg.
ASSET_ARGS=(
  generate
  --assetPath "$ROOT_DIR/assets"
  --iconBackgroundColor "#06183F"
  --iconBackgroundColorDark "#06183F"
  --splashBackgroundColor "#F7F9FD"
  --splashBackgroundColorDark "#06183F"
)
npx capacitor-assets "${ASSET_ARGS[@]}" --android
if [[ -d ios ]]; then
  npx capacitor-assets "${ASSET_ARGS[@]}" --ios
fi

echo "Capacitor mobile projects synchronized."
echo "App host: $APP_HOST"
echo "API base: $API_BASE"
echo "Android: npm run open:android"
if [[ -d ios ]]; then echo "iOS: npm run open:ios"; else echo "iOS generation requires macOS/Xcode."; fi
