#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLUGIN="@capgo/native-purchases@8.7.0"
PLUGIN_JAVA="$ROOT_DIR/node_modules/@capgo/native-purchases/android/src/main/java/ee/forgr/nativepurchases/NativePurchasesPlugin.java"

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

[[ -f "$PLUGIN_JAVA" ]] || {
  echo "Expected NativePurchases Android source not found. Refusing an unreviewed plugin layout." >&2
  exit 1
}

# NativePurchases 8.7.0 contains verbose Android debug statements that include
# Purchase.toString(), purchase tokens and order IDs. Purchase tokens are backend
# verification credentials and must never be written to device logs. Patch those
# diagnostics immediately after installation and fail closed if the reviewed
# source layout changes in a future plugin version.
node - "$PLUGIN_JAVA" <<'NODE'
const fs=require("fs");
const file=process.argv[2];
let source=fs.readFileSync(file,"utf8");
const sensitive=[
  '        Log.d(TAG, "Purchase details: " + purchase.toString());\n',
  '        Log.i(NativePurchasesPlugin.TAG, "handlePurchase" + purchase);\n',
  '        Log.d(TAG, "Purchase token: " + purchase.getPurchaseToken());\n',
  '            Log.d(TAG, "Resolving purchase call with transactionId: " + purchase.getPurchaseToken());\n',
  '        Log.d(TAG, "acknowledgePurchase() called with token: " + purchaseToken);\n',
  '                                Log.d(TAG, "Processing in-app purchase: " + purchase.getOrderId());\n',
  '                                Log.d(TAG, "Processing subscription purchase: " + purchase.getOrderId());\n',
];
for(const line of sensitive){
  if(!source.includes(line)){
    console.error(`Reviewed NativePurchases source changed; missing expected log line: ${line.trim()}`);
    process.exit(1);
  }
  source=source.replace(line,"");
}
fs.writeFileSync(file,source);
NODE

if grep -nE 'Log\.[a-zA-Z]+\([^;]*(getPurchaseToken|getOrderId|Purchase details:|handlePurchase" *\+ *purchase|purchaseToken)' "$PLUGIN_JAVA"; then
  echo "Sensitive Google Play purchase logging remains in NativePurchases. Aborting." >&2
  exit 1
fi

# Capacitor discovers the plugin from package metadata and wires the native
# Android implementation into the generated project. The pinned plugin uses
# Google Play Billing Library 9.1.x and exposes purchase, restore and subscription
# management operations consumed by frontend/src/lib/googlePlayPurchases.ts.
npx cap sync android
npx cap doctor

echo "Google Play Billing bridge prepared."
echo "Review and commit mobile/package.json and mobile/package-lock.json before release."
echo "Then complete the Play Console and backend service-account steps in mobile/PLAY_STORE.md."
