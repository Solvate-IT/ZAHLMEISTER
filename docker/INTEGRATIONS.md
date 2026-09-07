# Optional external integrations

Zahlmeister remains fully usable without these integrations. The normal/default mode opens the user's local communication apps and payments can be marked manually or matched from an imported statement.

## Infobip (internal messaging)

Internal SMS/WhatsApp/social messaging uses the customer's own Infobip account. Provider usage costs remain with that customer.

Preferred setup:

1. Create an Infobip Exchange/OAuth app for Zahlmeister.
2. Register this redirect URI:
   `https://<APP_HOST>/api/v1/communication-settings/infobip/oauth/callback`
3. Set `INFOBIP_OAUTH_CLIENT_ID` and `INFOBIP_OAUTH_CLIENT_SECRET` in `docker/.env`.
4. Users connect their own Infobip account under **Advanced communication**.
5. If the customer's Infobip account uses a personalized API base URL, enter it in the connection settings (for example `https://xxxxx.api.infobip.com`).

An API key remains available as a fallback. Credentials/tokens are encrypted with `APP_SECRET` before they are stored.

For internal email, users can alternatively configure their own SMTP/IMAP account. Port 465 is treated as SMTP-over-SSL, other SMTP ports use STARTTLS; port 993 uses IMAP-over-SSL.

## Ponto Connect (optional automatic BankSync)

Use **Ponto Connect** with Ponto's customer-paying model so the connected customer pays Ponto directly. Zahlmeister does not resell BankSync usage. The Ponto client id, client secret and mTLS certificate belong to the Zahlmeister installation. Individual Zahlmeister customers never enter those technical credentials; they authorize their own Ponto organization and selected bank accounts in Ponto's OAuth screen.

### Sandbox

Ponto routes sandbox versus live by the application credentials. The API and token endpoints use the same request format in both environments; the authorization page differs:

- Sandbox: `https://sandbox-authorization.myponto.com/oauth2/auth`
- Live: `https://authorization.myponto.com/oauth2/auth`

Development defaults to `PONTO_CONNECT_ENVIRONMENT=sandbox`. Production refuses a configured Ponto integration unless `PONTO_CONNECT_ENVIRONMENT=live`.

For the local Zahlmeister development stack:

1. Create a **sandbox application** in the Ibanity developer portal and enable Ponto Connect Account Information.
2. In the Ponto Connect product security settings, register the exact local callback used by Zahlmeister:
   `http://localhost:8003/api/v1/bank-sync/ponto/callback`
   If the developer portal requires a public HTTPS callback, expose the backend through a temporary HTTPS development hostname/tunnel and set the same URL in `OAUTH_CALLBACK_BASE_URL`. The registered URI and Zahlmeister's generated URI must match exactly.
3. Copy the sandbox `client_id` and `client_secret` to the local `docker/.env` only:
   - `PONTO_CONNECT_ENVIRONMENT=sandbox`
   - `PONTO_CONNECT_CLIENT_ID=...`
   - `PONTO_CONNECT_CLIENT_SECRET=...`
4. Put the sandbox mTLS credentials on the development machine as:
   - `docker/secrets/ponto/client.crt`
   - `docker/secrets/ponto/client.key`
   - set `PONTO_CONNECT_KEY_PASSWORD` only when the private key is encrypted.
5. Keep `PONTO_CONNECT_AUTHORIZE_URL` empty in development. Zahlmeister selects the official sandbox authorization URL from `PONTO_CONNECT_ENVIRONMENT`.
6. Rebuild/restart the backend and worker, sign in to Zahlmeister, open BankSync and choose **Ponto verbinden**.
7. Complete Ponto's sandbox authorization and select sandbox accounts. Ponto's sandbox uses fake institutions/accounts/transactions; the sandbox digipass response for adding/signing test accounts is `123456` according to Ponto's documentation.
8. After the redirect back to Zahlmeister, verify that the connection is `connected`, accounts are listed and **Jetzt synchronisieren** imports the sandbox transactions.

A safe authenticated diagnostic endpoint is available at:
`GET /api/v1/bank-sync/ponto/configuration`

It returns only environment, readiness, callback URI and names of missing configuration elements. It never exposes the client secret, certificate contents, private key or OAuth tokens.

The OAuth implementation uses a signed short-lived `state`, PKCE/S256, mTLS for token/API calls and encrypted token storage. Sandbox/live environment identity is stored with the connection; switching environments requires reconnecting so sandbox tokens can never silently be reused against live configuration. OAuth cancellation and provider errors are persisted as connection status/error information and redirect safely back to Zahlmeister.

Ponto's optional `onboarding_details_id` can later be used to prefill known customer information during Ponto onboarding. It is not required to execute the complete sandbox authorization/account-sync test and is therefore intentionally not coupled to the core BankSync flow.

The containers mount `docker/secrets/ponto` read-only at `/run/secrets/ponto`. `docker/.gitignore` excludes the certificate/private key; never commit them.

Zahlmeister does **not** trigger unattended bank synchronizations. Ponto refreshes account information itself; Zahlmeister only fetches the latest available data in the background. A user can also explicitly request a fetch from the advanced BankSync screen.

Ponto refresh tokens are rotated in a separate committed database transaction under a row lock, preventing two workers from consuming the same one-time refresh token.

Only an exact payment reference plus matching amount/currency is applied automatically. Ambiguous matches are exposed through the same review workflow as manually uploaded bank statements.

### Moving to live

Create/use a separate live Ponto application, register the production HTTPS callback, replace all sandbox client credentials and mTLS material with the live credentials, set `PONTO_CONNECT_ENVIRONMENT=live`, and keep the live authorization URL. Never copy sandbox tokens or customer connections into production; customers reconnect once against the live environment.

## Mollie Connect (optional online payments)

Online payments use **Mollie Connect**. Each Zahlmeister customer connects their own Mollie account through OAuth. The payment belongs to that connected merchant and Mollie bills its processing fees to that merchant; Zahlmeister does not hold customer funds or resell processing.

1. Register a Mollie OAuth app for Zahlmeister.
2. Register this redirect URI:
   `https://<APP_HOST>/api/v1/online-payments/mollie/oauth/callback`
3. Set `MOLLIE_OAUTH_CLIENT_ID` and `MOLLIE_OAUTH_CLIENT_SECRET` in `docker/.env`.
4. Required scopes are configured through `MOLLIE_OAUTH_SCOPES` and default to:
   `organizations.read profiles.read payments.read payments.write`
5. Customers connect their own Mollie account under **Payment > Advanced > Online payments**.
6. If an account has multiple payment profiles, the customer can choose one in the advanced view.
7. Apple Pay, Google Pay, cards and other methods are shown by Mollie's hosted checkout when they are available/enabled for that merchant profile.

Provider tokens are encrypted with `APP_SECRET`. Disconnecting attempts to revoke the refresh token at Mollie and always removes the local connection. `MOLLIE_TEST_MODE=true` can be used for sandbox/test payments where supported.

## Customer API

The customer API is part of the FastAPI backend and is disabled per organization by default. Customers enable it under **API & integrations**, create scoped credentials and call `/api/public/v1` with a Bearer API key. Keys are stored only as hashes; the raw key is returned once when created. Current scopes separate participant, collection and payment-status reads/writes.

The same API contracts are independent from the Next.js/Capacitor clients, so school, club, course and ERP systems can integrate without bypassing Zahlmeister business rules or tenant isolation.
