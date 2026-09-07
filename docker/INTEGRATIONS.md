# Optional external integrations

Zahlmeister remains usable without optional provider integrations. Bank transfers can be matched manually/imported, and external communication can open the user's local apps.

## Communication strategy

Zahlmeister deliberately supports only four participant communication channels:

- Email
- WhatsApp
- SMS
- Telegram

Instagram and Messenger are not part of the product communication model.

Each organization configures every channel once as **Internal**, **External** or **Disabled** and defines one global priority order. Collections do not contain their own channel configuration. For every participant Zahlmeister selects the first usable channel from the organization's order.

Participant-specific channel knowledge is sparse and learned over time:

- Email with an address is available by default.
- SMS with a phone number is available by default.
- WhatsApp with a phone number starts as unknown because normal clients cannot reliably query whether a number is registered with WhatsApp.
- Telegram is available when a username is stored.
- Explicitly learned or manually changed `available`/`unavailable` states are stored per participant/channel.
- Changing the relevant email address, phone number or Telegram username resets learned knowledge for that address.

No rows are created for every participant/channel combination up front. Overrides are batch-loaded for collection dispatch, so lists with hundreds or thousands of participants do not create N+1 queries or unnecessary configuration rows.

For external sending the current client also constrains what can be used. Desktop web allows Email, WhatsApp Web/Desktop and Telegram, but external SMS is intentionally not offered. Native/mobile clients can also use SMS. If an external WhatsApp attempt is confirmed as unavailable, Zahlmeister stores that knowledge and immediately resolves the next channel for that participant.

Telegram is supported as an external channel only. Initiating arbitrary Telegram conversations server-side is not a reliable general-purpose workflow, so internal Telegram sending is intentionally disabled.

## Central Zahlmeister email

**Send via Zahlmeister** is the default internal email path. All organizations use the same technically verified platform sender address/domain. The visible sender name is the customer's organization name.

Every outgoing central email receives an opaque HMAC-protected Reply-To alias such as:

`reply+<opaque-token>@<MAIL_REPLY_DOMAIN>`

The token contains no readable participant, collection or organization identifiers. Production mail routing must deliver `reply+*@<MAIL_REPLY_DOMAIN>` to the central mailbox configured with `PLATFORM_IMAP_*`. The worker polls that mailbox and attaches valid replies directly to the original collection participant's communication history.

Required production settings include:

- `MAIL_FROM_ADDRESS`
- `MAIL_REPLY_DOMAIN`
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD_FILE`, `SMTP_STARTTLS`
- `PLATFORM_IMAP_HOST`, `PLATFORM_IMAP_PORT`, `PLATFORM_IMAP_USERNAME`, `PLATFORM_IMAP_PASSWORD_FILE`
- `PLATFORM_IMAP_SSL` or `PLATFORM_IMAP_STARTTLS`
- `PLATFORM_IMAP_FOLDER`

Development uses Mailpit for SMTP. Mailpit is SMTP-only, so central reply import is disabled locally unless a development IMAP mailbox is explicitly configured.

## Own SMTP/IMAP account

An organization can use its own email server instead of the central Zahlmeister sender. SMTP supports SSL or STARTTLS. IMAP is optional for custom accounts and, when configured, imports replies into the matching participant communication history. Credentials are encrypted with `APP_SECRET` before storage.

## Microsoft 365

Microsoft 365 mailboxes use Microsoft Graph with delegated OAuth 2.0/PKCE. Zahlmeister stores encrypted OAuth access/refresh tokens, never the customer's Microsoft password. MFA and tenant sign-in policies remain in Microsoft's login flow.

Create one multi-tenant Microsoft Entra web application for Zahlmeister. `MICROSOFT365_TENANT=organizations` is the default. Register these redirect URIs as applicable:

- Development: `http://localhost:8003/api/v1/communication-settings/microsoft365/oauth/callback`
- Production: `https://<APP_HOST>/api/v1/communication-settings/microsoft365/oauth/callback`

Delegated scopes:

- `User.Read`
- `Mail.ReadWrite`
- `Mail.Send`
- `offline_access`
- `openid`
- `profile`

Development uses `MICROSOFT365_CLIENT_ID` and `MICROSOFT365_CLIENT_SECRET` in the ignored local `docker/.env`. Production stores the secret in an untracked file and sets `MICROSOFT365_CLIENT_SECRET_FILE`.

Outgoing messages are sent through Microsoft Graph. The worker reads the connected Inbox and links replies through Microsoft message/conversation identifiers. SMTP AUTH or IMAP Basic Authentication is not used for Microsoft 365. The current implementation targets the connected user's mailbox; shared mailbox support remains intentionally separate.

## Infobip

Infobip is optional for internal **SMS and WhatsApp**. Provider usage costs remain with the customer's Infobip account.

Preferred setup:

1. Create an Infobip Exchange/OAuth app for Zahlmeister.
2. Register `https://<APP_HOST>/api/v1/communication-settings/infobip/oauth/callback`.
3. Configure `INFOBIP_OAUTH_CLIENT_ID` and its secret.
4. The customer connects their Infobip account and configures the sender/resource for SMS and/or WhatsApp.

An API key remains available as a fallback. Provider credentials/tokens are encrypted with `APP_SECRET`.

WhatsApp is not marked available merely because Infobip accepted a send request. Delivery/read events or an inbound WhatsApp reply establish availability. A failed delivery only marks WhatsApp unavailable when the provider payload explicitly identifies a permanent destination problem such as an unregistered/invalid WhatsApp recipient; generic transient failures never permanently disable the participant channel.

## Ponto Connect (optional automatic BankSync)

Use **Ponto Connect** with Ponto's customer-paying model so the connected customer pays Ponto directly. Zahlmeister does not resell BankSync usage. The Ponto client id, client secret and mTLS certificate belong to the Zahlmeister installation. Individual customers authorize their own Ponto organization and selected bank accounts through OAuth.

### Sandbox

- Sandbox authorization: `https://sandbox-authorization.myponto.com/oauth2/auth`
- Live authorization: `https://authorization.myponto.com/oauth2/auth`

Development defaults to `PONTO_CONNECT_ENVIRONMENT=sandbox`. Production rejects configured sandbox Ponto credentials.

Local sandbox setup:

1. Create a sandbox application in the Ibanity developer portal and enable Ponto Connect Account Information.
2. Register `http://localhost:8003/api/v1/bank-sync/ponto/callback`, or use an HTTPS development hostname and set exactly the same value through `OAUTH_CALLBACK_BASE_URL` if required by the portal.
3. Set `PONTO_CONNECT_ENVIRONMENT=sandbox`, client id and client secret in ignored `docker/.env`.
4. Store the sandbox mTLS certificate/key as `docker/secrets/ponto/client.crt` and `client.key`; set `PONTO_CONNECT_KEY_PASSWORD` only for an encrypted key.
5. Keep `PONTO_CONNECT_AUTHORIZE_URL` empty in development so the environment selects the official sandbox URL.
6. Connect Ponto in Zahlmeister, authorize sandbox accounts and run a sync.

`GET /api/v1/bank-sync/ponto/configuration` is an authenticated diagnostic endpoint that reports only readiness, environment, callback URI and missing configuration names. It never exposes secrets or tokens.

The OAuth implementation uses signed short-lived state, PKCE/S256, mTLS for token/API calls and encrypted token storage. Refresh tokens are rotated under a database row lock. The worker periodically fetches fresh Ponto data for connected accounts, and users can also request a sync explicitly. Only an exact payment reference plus matching amount/currency is applied automatically; ambiguous candidates remain for review.

### Moving Ponto to live

Use a separate live Ponto application, register the production HTTPS callback, replace all sandbox credentials/certificates with live material, set `PONTO_CONNECT_ENVIRONMENT=live` and reconnect customers. Never reuse sandbox tokens in production.

## Mollie Connect (optional online payments)

Online payments use **Mollie Connect**. Each Zahlmeister customer connects their own Mollie account through OAuth. The payment belongs to that merchant and Mollie charges processing fees to that merchant; Zahlmeister does not hold customer funds.

1. Register a Mollie OAuth app.
2. Register `https://<APP_HOST>/api/v1/online-payments/mollie/oauth/callback`.
3. Configure the client id/secret.
4. Default scopes are `organizations.read profiles.read payments.read payments.write`.
5. Customers connect their Mollie account and, when needed, select a payment profile.

Provider tokens are encrypted with `APP_SECRET`. `MOLLIE_TEST_MODE=true` can be used for test payments where supported.

## Customer API

The customer API is disabled per organization by default. Customers can enable it under **API & integrations**, create scoped credentials and call `/api/public/v1` with a Bearer API key. Raw keys are returned once and only hashes are persisted. The API uses the same business rules and tenant isolation as the Next.js/Capacitor clients.
