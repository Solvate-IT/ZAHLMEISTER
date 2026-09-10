#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLUGIN_DIR="$ROOT_DIR/node_modules/@capgo/native-purchases"
PLUGIN_PACKAGE="$PLUGIN_DIR/package.json"
PLUGIN_JAVA="$PLUGIN_DIR/android/src/main/java/ee/forgr/nativepurchases/NativePurchasesPlugin.java"
EXPECTED_VERSION="8.7.0"

# The plugin is intentionally installed only when Google Play preparation is
# requested. Ordinary mobile npm installs before that point therefore have
# nothing to harden.
[[ -d "$PLUGIN_DIR" ]] || exit 0
[[ -f "$PLUGIN_PACKAGE" && -f "$PLUGIN_JAVA" ]] || {
  echo "NativePurchases layout is incomplete. Refusing an unreviewed Android billing build." >&2
  exit 1
}

version="$(node -p "require(process.argv[1]).version" "$PLUGIN_PACKAGE")"
[[ "$version" == "$EXPECTED_VERSION" ]] || {
  echo "NativePurchases $version is not the reviewed version $EXPECTED_VERSION." >&2
  exit 1
}

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
for(const line of sensitive) source=source.replaceAll(line,"");
fs.writeFileSync(file,source);
NODE

if grep -nE 'Log\.[a-zA-Z]+\([^;]*(getPurchaseToken|getOrderId|Purchase details:|handlePurchase" *\+ *purchase|purchaseToken)' "$PLUGIN_JAVA"; then
  echo "Sensitive Google Play purchase logging remains in NativePurchases. Aborting." >&2
  exit 1
fi
