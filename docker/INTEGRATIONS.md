# Optional external integrations

Zahlmeister remains usable without optional provider integrations. Bank transfers can be matched manually/imported, and external communication can open the user's local apps.

## Communication strategy

Zahlmeister deliberately supports only four participant communication channels:

- Email
- WhatsApp
- SMS
- Telegram

Instagram and Messenger are not part of the product communication model.

Each organization configures every channel once as **Internal**, **External** or **Disabled** and defines one global priority order. Collections use this order by default; an explicit collection channel remains available only as an advanced override. For every participant Zahlmeister selects the first usable channel from the effective order.

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

## Multilingual message templates

Message templates support all Zahlmeister UI languages. A custom template starts with one source text instead of copying the generic system message into every language. Every language version remains editable independently.

Participants can optionally store a preferred message language. Message rendering uses this fallback order:

1. participant language,
2. organization language,
3. English,
4. built-in system template for the requested language.

Participant locale preferences are stored separately from contact data and batch-loaded for collection dispatch, avoiding N+1 queries. Existing participants without a preference continue to use the organization language.

Automatic translation is optional and platform-wide. Configure `GOOGLE_TRANSLATE_API_KEY` in development or `GOOGLE_TRANSLATE_API_KEY_FILE` in production. The credential belongs to the Zahlmeister installation and is never exposed in organization settings or the frontend. `GOOGLE_TRANSLATE_API_URL` defaults to the official Cloud Translation Basic endpoint.

When automatic translation is enabled, the source language can be detected automatically. Zahlmeister generates only language versions that are still missing. Existing or manually edited translations are never overwritten by the bulk translation action. Template variables such as `{{first_name}}`, `{{amount}}` and `{{payment_link}}` are replaced with protected markers before translation and must match exactly after translation; otherwise the result is rejected and nothing is stored.

Translation happens only when a template is created or when the user explicitly requests missing translations. Sending a collection does not call the translation provider; completed translations are stored in PostgreSQL.

The built-in/default message template remains protected from deletion. Non-default templates may be deleted.

## Central Zahlmeister email

**Send via Zahlmeister** is the default internal email path and uses the explicit backend provider `zahlmeister_email`. All organizations use the same technically verified platform sender address/domain. Platform SMTP/IMAP credentials stay in installation secrets and are never copied into organization settings or returned to the frontend. Older organization rows that represented the platform sender as `smtp_imap` with an empty tenant configuration are normalized transparently for backwards compatibility.

The visible sender name is the customer's organization name. Every outgoing central email receives an opaque HMAC-protected Reply-To alias such as:

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

An organization can use its own email server instead of the central Zahlmeister sender. This is the separate `smtp_imap` provider. SMTP supports SSL or STARTTLS. IMAP is optional for custom accounts and, when configured, imports replies into the matching participant communication history. Credentials are encrypted with `APP_SECRET` before storage.

## Microsoft 365

Microsoft 365 mailboxes use Microsoft Graph with delegated OAuth 2.0/PKCE. Zahlmeister stores encrypted OAuth access/refresh tokens, never the customer's Microsoft password. MFA and tenant sign-in policies remain in Microsoft's login flow.

Create one multi-tenant Microsoft Entra web application for Zahlmeister. `MICROSOFT365_TENANT=organizations` is the default. Register these redirect URIs as applicable:

- Development: `http://localhost:8003/api/v1/communication-settings/microsoft365/oauth/callback`
- Production: `https://<APP_HOST>/api/v1/communication-settings/microsoft365/oauth/callback`

Delegated scopes:

- `User.Read`
- `Mail.Read`
- `Mail.Send`
- `offline_access`
- `openid`
- `profile`

`Mail.ReadWrite` is intentionally not required. Outgoing mail uses Graph `sendMail` directly instead of creating mailbox drafts. Each outgoing MIME message receives a stable RFC `Message-ID` derived from the Zahlmeister communication record. The worker reads the connected Inbox and links replies through `In-Reply-To`/`References` and Microsoft conversation metadata.

Development uses `MICROSOFT365_CLIENT_ID` and `MICROSOFT365_CLIENT_SECRET` in the ignored local `docker/.env`. Production stores the secret in an untracked file and sets `MICROSOFT365_CLIENT_SECRET_FILE`.

SMTP AUTH or IMAP Basic Authentication is not used for Microsoft 365. The current implementation targets the connected user's mailbox; shared mailbox permissions are intentionally not requested until shared-mailbox support is actually enabled.

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

Use **Ponto Connect** with Ponto's customer-paying model so the connected customer pays Ponto directly. Zahlmeister does not resell BankSync usage. The Ponto client id, client secret and mTLS certificate belong to the Zahlmeister installation. Individual customers authorize their own Ponto organization and selected bank accounts through OAuth; they never enter Ponto API credentials in Zahlmeister.

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

Ponto's optional integrated onboarding/prefill may be added on top of this OAuth flow without changing the BankSync architecture. Do not make VAT/company fields mandatory in Zahlmeister solely for Ponto until Ponto has confirmed that the customer-paying model supports the intended individual teacher/private-person customer segment and clarified the required onboarding data for that segment.

### Moving Ponto to live

Use a separate live Ponto application, register the production HTTPS callback, replace all sandbox credentials/certificates with live material, set `PONTO_CONNECT_ENVIRONMENT=live` and reconnect customers. Never reuse sandbox tokens in production.

## OAuth callback base

`PUBLIC_APP_URL` is the public frontend URL and is not implicitly the production OAuth callback configuration. Set `OAUTH_CALLBACK_BASE_URL` explicitly in production to the public base that routes `/api/v1/.../callback` to the FastAPI backend. Development may use the direct backend base such as `http://localhost:8003`.

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
