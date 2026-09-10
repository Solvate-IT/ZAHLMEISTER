# Android / Google Play release handoff

This document is the handoff for finishing the Zahlmeister Android app and publishing it through
Google Play. The Android application ID is fixed to `at.solvate.zahlmeister`.

## Billing model

Zahlmeister Pro is a digital subscription. Inside the Android app it must therefore use Google Play
Billing, not a direct Google Pay/Mollie checkout. Google Pay may appear to the customer as a payment
method inside Google Play, but Zahlmeister talks to the Play Billing subscription APIs.

The shared product contract is:

- Google Play subscription product ID: `zahlmeister.pro.yearly`
- Base plan ID: `yearly`
- Billing period: yearly / 12 months
- Android package: `at.solvate.zahlmeister`

Do not rename the product ID after publishing. Backend, frontend and Play Console must use the same
identifier. The customer-facing price displayed in Android must come from Google Play ProductDetails,
not from the web/Mollie tariff response.

## 1. Generate and open Android project

From the repository root:

```bash
./mobile/tool/bootstrap_mobile.sh zahlmeister.solvate.at https://zahlmeister.solvate.at/api/v1
cd mobile
npm run prepare:google-play
npm run open:android
```

`prepare:google-play` installs `@capgo/native-purchases@8.7.0`, updates the npm lockfile and runs
`cap sync android`. Review and commit the resulting `mobile/package.json`, `mobile/package-lock.json`
and generated Android project changes on `development` before releasing.

The frontend-side native bridge is already prepared in
`frontend/src/lib/googlePlayPurchases.ts`. Purchases are started with the Zahlmeister organization
UUID as the obfuscated Google Play account identifier and with automatic client-side acknowledgement
disabled. The backend verifies the purchase first and acknowledges it server-side.

## 2. Play Console subscription

In Play Console, create the app for package `at.solvate.zahlmeister`, then create the subscription
under Monetize with Play > Products > Subscriptions:

1. Subscription product ID: `zahlmeister.pro.yearly`.
2. Create an auto-renewing base plan with ID `yearly` and a one-year billing period.
3. Configure the intended countries/regions and local prices.
4. Activate the base plan.
5. Do not add introductory/free-trial offers unless the application UI and backend rules are updated
   intentionally for them. The prepared client selects the ordinary base-plan offer first.

The Android UI must clearly show Play's localized price and yearly billing frequency before purchase,
and must provide access to Google Play subscription management/cancellation.

## 3. Google Play Developer API service account

Create a dedicated Google Cloud service account for Zahlmeister Play Billing and enable the Google
Play Android Developer API for its Cloud project. Add/grant that service account access in Play
Console only to the Zahlmeister app. It needs access to the Purchases API and the permissions required
to acknowledge subscription purchases; do not grant general administrator access just for billing.

Download one JSON credential only when provisioning the server. Store it outside Git as:

```text
docker/secrets/production/google_play_service_account.json
```

For a development installation use:

```text
docker/secrets/development/google_play_service_account.json
```

The existing Docker mount exposes the file inside backend/worker containers as:

```text
/run/secrets/internal/google_play_service_account.json
```

Never place the JSON in `mobile/`, `frontend/`, an Android resource, environment committed to Git, or
Play Store build artifacts.

Backend endpoints prepared for the Android client:

```text
GET  /api/v1/billing/purchase-context?provider=google
GET  /api/v1/billing/google/config
POST /api/v1/billing/google/verify
POST /api/v1/billing/google/sync
POST /api/v1/billing/google/rtdn       (Google Pub/Sub only)
```

`POST /billing/google/verify` accepts only the purchase token from the authenticated app. Product,
account, price, status, expiry and renewal state are read from Google server-side and are not trusted
from the device.

## 4. Real-time developer notifications

Configure Google Play Real-time developer notifications (RTDN) with Google Cloud Pub/Sub. Use an
authenticated push subscription to:

```text
https://zahlmeister.solvate.at/api/v1/billing/google/rtdn
```

Configure Pub/Sub push authentication with the same dedicated service account used for the Android
Publisher API and use the push endpoint above as the OIDC audience. Ensure the Pub/Sub service agent
is allowed to mint an identity token for that service account.

The backend verifies the Google-signed OIDC token, package name and purchase against the Google Play
Developer API. Cancellation, grace period, account hold and expiry therefore update the central
`StoreSubscription`, so the same state is visible in web, Android and later iOS.

Send a Play Console test notification and confirm HTTP 204 before production rollout.

## 5. Client flow to finish

The remaining Android UI wiring should use this sequence:

1. Load `/billing/purchase-context?provider=google` and `/billing/google/config`.
2. Only offer a new purchase when `purchase_allowed` and Google billing are available.
3. Read the localized base-plan price with `getGooglePlayOffer()`.
4. Start the purchase with `purchaseGooglePlayPro(config, account_token)`.
5. Send the returned token to `POST /billing/google/verify` as
   `{"purchase_token":"..."}`.
6. Refresh `/billing/entitlement`; Pro is granted only after server verification.
7. On Android app start/resume, query `currentGooglePlayPurchaseTokens()` when necessary and submit an
   unlinked current purchase to `/billing/google/verify`. For an already linked Google subscription,
   `/billing/google/sync` can refresh the server state directly.
8. Use `manageGooglePlaySubscriptions()` for the user's manage/cancel action.

Do not acknowledge a new purchase in the app before backend verification. The backend acknowledges a
verified Play purchase. If verification fails, do not grant Pro locally.

## 6. Test matrix before production

Use a Play Console internal testing track and license testers. At minimum verify:

- clean installation and login;
- annual Pro product and localized price load correctly;
- successful purchase activates the same Zahlmeister account on Android and web;
- pending purchase does not activate Pro prematurely;
- reinstall/login restores the existing subscription;
- cancelling renewal in Google Play leaves Pro active until paid expiry and shows renewal disabled;
- grace period remains entitled;
- account hold/expiry removes entitlement according to the backend state;
- RTDN updates web state without requiring the Android app to be opened;
- a purchase bound to another Zahlmeister organization is rejected;
- a Mollie/other-provider Pro entitlement cannot accidentally create a second active subscription;
- server-side acknowledgement succeeds and test purchases are not automatically refunded;
- no service-account JSON, purchase token or authentication token appears in logs/build artifacts.

## 7. Store release

Before uploading the production AAB, finish the normal Play Console release requirements: Play App
Signing/upload key, app version/versionCode, store listing and screenshots, privacy policy, Data
Safety declaration, content rating, target audience, app access instructions where required, and the
subscription disclosures/cancellation path.

Publish to an internal test track first. Promote the exact tested build to production only after the
billing test matrix and backend production configuration are verified.
