# Zahlmeister Mobile

The mobile apps are thin Capacitor shells around the same statically exported Next.js/React UI used by the web application. Business logic and authorization stay in the FastAPI backend.

## Bootstrap

From the project root, with `frontend/` and `mobile/` next to each other:

```bash
./mobile/tool/bootstrap_mobile.sh app.example.com https://app.example.com/api/v1
```

The script builds the production frontend for the native API endpoint, creates/synchronizes the Capacitor Android project, and on macOS also the iOS project. Android Studio/Xcode projects are then opened with `npm run open:android` or `npm run open:ios` from `mobile/`.

The application ID/bundle ID is `at.solvate.zahlmeister`. HTTPS App/Universal Links and the `zahlmeister://` custom scheme are configured by the bootstrap script. Payment and account-action links still remain ordinary HTTPS URLs and therefore continue to work in a browser when an app is not installed.

Before store release, publish the association files documented under `mobile-links/`, configure Android/iOS signing, and commit the generated native projects after the first successful bootstrap so subsequent native customizations are reviewable.
