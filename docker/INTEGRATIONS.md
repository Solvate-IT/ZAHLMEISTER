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

Use **Ponto Connect** with Ponto's customer-paying model so the connected customer pays Ponto directly. Zahlmeister does not resell BankSync usage.

1. Create a Ponto Connect application in the Ibanity developer portal (sandbox first).
2. Register this redirect URI:
   `https://<APP_HOST>/api/v1/bank-sync/ponto/callback`
3. Put the Ponto Connect mTLS credentials on the server as:
   - `docker/secrets/ponto/client.crt`
   - `docker/secrets/ponto/client.key`
4. Set `PONTO_CONNECT_CLIENT_ID` and `PONTO_CONNECT_CLIENT_SECRET` in `docker/.env`.
5. Do not commit the certificate/private key. `docker/.gitignore` excludes them.

The containers mount `docker/secrets/ponto` read-only at `/run/secrets/ponto`.

Zahlmeister does **not** trigger unattended bank synchronizations. Ponto refreshes account information itself; Zahlmeister only fetches the latest available data in the background. A user can also explicitly request a fetch from the advanced BankSync screen.

Ponto refresh tokens are rotated in a separate committed database transaction under a row lock, preventing two workers from consuming the same one-time refresh token.

Only an exact payment reference plus matching amount/currency is applied automatically. Ambiguous matches are exposed through the same review workflow as manually uploaded bank statements.

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
