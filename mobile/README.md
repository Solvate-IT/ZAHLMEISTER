# Zahlmeister Mobile

The mobile apps are thin Capacitor shells around the same statically exported Next.js/React UI used by the web application. Business logic, authorization and subscription entitlement decisions stay in the FastAPI backend.

## Building the Android app

Everything runs in Docker; the host needs no Node, JDK, Android SDK or adb. From the project root:

```bash
./docker/manage.sh        # 11) Android App (APK / AAB)
```

| Option | Output | Use |
|---|---|---|
| 1) Debug APK | `mobile/dist/debug/Zahlmeister.apk` | install on a phone, debugging |
| 2) Debug AAB | `mobile/dist/debug/Zahlmeister.aab` | Play internal app sharing, bundle tests |
| 3) Release APK | `mobile/dist/release/Zahlmeister.apk` | direct install for testers |
| 4) Release AAB | `mobile/dist/release/Zahlmeister.aab` | Google Play upload |
| 5) Device | — | install, start, stop, log and DevTools on a USB phone |
| 6) Create upload keystore | `docker/secrets/android/` | once, before the first Play upload |
| 7) Rebuild Android build image | — | force a fresh toolchain image |

Each option builds only the file it names and replaces the previous build of that name; version and signer are printed after the build.

The toolchain is the `mobile` service in `docker/compose.yml` (profile `tools`, stage `mobile` of `docker/Dockerfile`): Node 24, JDK 21, the Android SDK with adb, bundletool and the npm dependencies of `frontend/` and `mobile/`, including the Capacitor CLI. Every build first runs `compose build mobile`, a cache hit unless a lockfile changed. `mobile/tool/build_android.sh` then copies the read-only mounted sources into the container, builds the static frontend, runs `cap sync android` and Gradle, and prints the artifact's signer. Gradle runs at warning level, so a successful build prints no task list; compiler warnings of the Capacitor plugins in `node_modules` are silenced in `android/build.gradle`, those of `:app` are kept. Gradle downloads are kept in the `mobile_gradle` volume, the debug signing key and adb key in `mobile_android_user`. Ctrl-C stops a running build.

The app is built against the production API from `docker/.env.production` (`PUBLIC_APP_URL` + `/api/v1`). Override it with an HTTPS URL for a single build: `MOBILE_API_BASE_URL=https://staging.example/api/v1 ./docker/manage.sh`.

### Phone (option 5, Linux hosts)

The `mobile-device` service runs adb and bundletool from the same image against a USB-connected phone:

| Device option | What it does |
|---|---|
| 1) Show connected devices | `adb devices -l` |
| 2) Install a build | pick one of `mobile/dist/*/Zahlmeister.*`; an APK installs directly, an AAB is cut by bundletool into the split APKs Google Play would deliver to this phone |
| 3) / 4) Start / Stop app | launch or force-stop `at.solvate.zahlmeister` |
| 5) App log | logcat of the running app (Ctrl-C to stop) |
| 6) WebView DevTools | forwards the app's WebView to Chrome (Ctrl-C to stop) |
| 7) Clear app data | fresh start, logged out |
| 8) Uninstall app | |
| 9) adb shell | |

Once per phone: *Settings → About phone →* tap *Build number* seven times, then *Developer options → USB debugging*. Connect it by USB and accept *Allow USB debugging?* with *Always allow from this computer*; the key is kept in the `mobile_android_user` volume. With several phones attached, start `manage.sh` with `ANDROID_SERIAL=<serial>`.

adb in the container owns the phone's USB connection, so no other adb server may run on the host (`adb kill-server`, close Android Studio's device manager). It runs as root because `/dev/bus/usb` nodes are root-owned without Android udev rules; the service may open only USB character devices. It uses host networking, so its adb server (localhost:5037) and the DevTools forward (localhost:9222) are reachable from the host's Chrome.

**Debugging.** Debug builds are debuggable, so Capacitor enables WebView debugging. Install `debug/Zahlmeister.apk` (or the debug AAB), choose *WebView DevTools* and open `chrome://inspect/#devices` in Chrome on the same computer: *Zahlmeister* is listed under the phone or as a remote target on `localhost:9222`; *inspect* opens DevTools for the running app while the app log scrolls in the terminal. Release builds expose no DevTools.

Install signatures: an APK keeps the signature it was built with; bundletool signs the APKs it cuts from a debug AAB with the same debug key and those from a release AAB with the upload key (the debug key if there is none). A build signed with another key — for example the Play Store version — must be uninstalled first (8). Google Play accepts debuggable bundles only through internal app sharing, never on a testing or production track.

### Signing

Release builds are signed with the upload key in `docker/secrets/android/` (`upload-keystore.jks` and `key.properties`, both gitignored), created by option 6 with an ASCII password. `mobile/android/app/build.gradle` follows the Sawmill contract: with no `key.properties` a release is signed with the debug key and a banner says so; an incomplete one fails the build. Back up the keystore and its password outside the build machine — it is the only key that can sign updates of the published app. Enable Play App Signing on the first upload.

`versionName` follows `mobile/package.json`. Raise `versionCode` in `mobile/android/app/build.gradle` before every Play upload.

## Native project

`mobile/android/` is generated source and committed so native changes stay reviewable. It was created with:

```bash
./mobile/tool/bootstrap_mobile.sh zahlmeister.solvate.at https://zahlmeister.solvate.at/api/v1
```

The script builds the production frontend, creates or synchronizes the Capacitor Android project (on macOS also iOS), writes the HTTPS App Link and `zahlmeister://` intent filters for the given host and generates the launcher icons from `assets/logo.svg`. Re-run it (on the host or inside the build image) only to regenerate these parts, then review the diff and restore the signing block in `app/build.gradle` if it was replaced. Android Studio opens the project with `npm run open:android` from `mobile/`.

The application ID/bundle ID is `at.solvate.zahlmeister`. HTTPS App/Universal Links and the `zahlmeister://` custom scheme are configured by the bootstrap script. Payment and account-action links remain ordinary HTTPS URLs and therefore continue to work in a browser when an app is not installed.

## Android / Google Play Billing

After the Android project has been generated, prepare the native Google Play Billing bridge with:

```bash
cd mobile
npm run prepare:google-play
```

Zahlmeister Pro is a digital subscription and therefore uses Google Play Billing inside the Android app. The setup, product/base-plan contract, backend service account, real-time developer notifications, test matrix and Play Store release handoff are documented in [`PLAY_STORE.md`](./PLAY_STORE.md).

Before store release, create the upload keystore (`manage.sh` → 11 → 6) and configure iOS signing in Xcode.
