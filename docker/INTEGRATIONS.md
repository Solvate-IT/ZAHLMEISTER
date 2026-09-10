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

Automatic translation is optional and platform-wide. Configure `GOOGLE_TRANSLATE_API_KEY` as an external credential in the ignored `docker/.env`. The credential belongs to the Zahlmeister installation and is never exposed in organization settings or the frontend. The backend uses the official Cloud Translation Basic endpoint by default.

When automatic translation is enabled, the source language can be detected automatically. Zahlmeister generates only language versions that are still missing. Existing or manually edited translations are never overwritten by the bulk translation action. Template variables are replaced with protected markers before translation and must match exactly after translation; otherwise the result is rejected and nothing is stored.

Translation happens only when a template is created or when the user explicitly requests missing translations. Sending a collection does not call the translation provider; completed translations are stored in PostgreSQL.

The built-in/default message template remains protected from deletion. Non-default templates may be deleted.

## Central Zahlmeister email

**Send via Zahlmeister** is the default internal email path and uses the explicit backend provider `zahlmeister_email`. All organizations use the same technically verified platform sender address/domain. Platform SMTP/IMAP credentials stay in installation credentials and are never copied into organization settings or returned to the frontend. Older organization rows that represented the platform sender as `smtp_imap` with an empty tenant configuration are normalized transparently for backwards compatibility.

The visible sender name is the customer's organization name. Every outgoing central email receives an opaque HMAC-protected Reply-To alias such as:

`reply+<opaque-token>@<MAIL_REPLY_DOMAIN>`

The token contains no readable participant, collection or organization identifiers. Production mail routing must deliver `reply+*@<MAIL_REPLY_DOMAIN>` to the central mailbox configured with `PLATFORM_IMAP_*`.

Non-secret SMTP/IMAP settings are kept in `.env.development` and `.env.production`. Real credentials such as `SMTP_PASSWORD` and `PLATFORM_IMAP_PASSWORD` belong only in ignored `docker/.env`.

Development uses Mailpit for SMTP. Mailpit is SMTP-only, so central reply import is disabled locally unless a development IMAP mailbox is explicitly configured.

## Own SMTP/IMAP account

An organization can use its own email server instead of the central Zahlmeister sender. This is the separate `smtp_imap` provider. SMTP supports SSL or STARTTLS. IMAP is optional for custom accounts and, when configured, imports replies into the matching participant communication history. Credentials are encrypted with `APP_SECRET` before storage.

## Microsoft 365

Microsoft 365 mailboxes use Microsoft Graph with delegated OAuth 2.0/PKCE. Zahlmeister stores encrypted OAuth access/refresh tokens, never the customer's Microsoft password. MFA and tenant sign-in policies remain in Microsoft's login flow.

Create one multi-tenant Microsoft Entra web application for Zahlmeister. Register these redirect URIs as applicable:

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

`MICROSOFT365_CLIENT_ID` and `MICROSOFT365_CLIENT_SECRET` are external credentials in ignored `docker/.env`. SMTP AUTH or IMAP Basic Authentication is not used for Microsoft 365.

## Infobip

Infobip is optional for internal **SMS and WhatsApp**. Provider usage costs remain with the customer's Infobip account. The implementation uses Infobip Exchange OAuth, Messages API and CPaaS X Subscriptions.

### Platform OAuth setup

1. Create an Infobip Exchange/OAuth app for Zahlmeister.
2. Register `https://<APP_HOST>/api/v1/communication-settings/infobip/oauth/callback`.
3. Configure `INFOBIP_OAUTH_CLIENT_ID` and `INFOBIP_OAUTH_CLIENT_SECRET` in ignored `docker/.env`.
4. Required scopes are `api_read message:send subscriptions:manage`.
5. The customer connects the Infobip account and selects the sender/resource used for SMS and/or WhatsApp.

An API key remains available as a fallback. Provider credentials/tokens and managed subscription metadata are encrypted with `APP_SECRET`. OAuth uses the provider-returned personalized `*.api.infobip.com` base URL when available; the connection can also be corrected explicitly to the account's personalized HTTPS base URL.

### Webhooks and replies

For a public HTTPS installation, Zahlmeister creates a sender-scoped CPaaS X subscription when internal SMS or WhatsApp is configured:

- SMS: `DELIVERY`, `INBOUND_MESSAGE`
- WhatsApp: `DELIVERY`, `SEEN`, `INBOUND_MESSAGE`

Each managed subscription has its own deterministic notification profile and Basic-auth setting. The Basic password is the existing random per-connection webhook key and is never exposed in the UI as a credential. Zahlmeister verifies this authentication on the webhook endpoint. Direct per-message webhook URLs are intentionally not set because Infobip documents that they override CPaaS X subscription routing.

When an internal Infobip channel is changed or the Infobip connection is deleted, Zahlmeister removes its managed subscription, notification profile and authentication setting before removing local connection data. If remote cleanup fails, the local connection is retained and the disconnect fails visibly instead of leaving an unknown remote configuration.

If `PUBLIC_APP_URL` is localhost/non-public, CPaaS X webhook registration is skipped. Provider-to-Zahlmeister webhook behavior therefore needs to be tested on the public test installation.

Depending on the Infobip number/sender configuration, inbound forwarding may need **Follow subscription** enabled in Infobip. This is particularly relevant if a number already has a number-specific inbound forwarding rule.

WhatsApp is not marked available merely because Infobip accepted a send request. Delivery/read events or an inbound WhatsApp reply establish availability. A failed delivery only marks WhatsApp unavailable when the provider payload explicitly identifies a permanent destination problem; generic transient failures never permanently disable the participant channel.

### Required WhatsApp Utility template

Business-initiated WhatsApp messages outside the customer-initiated 24-hour window must use a Meta-approved template. Zahlmeister therefore does **not** send the initial payment request as an arbitrary free-form WhatsApp message.

Register this template for every language that will be used on the selected WhatsApp sender:

- Name: `zahlmeister_payment_request`
- Category: `UTILITY`
- Type: text

German body:

```text
Hallo {{1}},

bitte bezahle {{2}} für {{3}}.

Hier bezahlen: {{4}}
Zahlungsreferenz: {{5}}

Mit freundlichen Grüßen
{{6}}
```

Placeholder contract:

1. participant/contact name
2. formatted amount and currency
3. collection name
4. Zahlmeister payment link
5. payment reference
6. sender/account display name

The language code registered in Infobip/Meta must match the participant language sent by Zahlmeister (`de`, `en`, `fr`, etc.). Meta approval is external and cannot be bypassed by Zahlmeister. Register and approve at least the languages used during acceptance testing before testing internal WhatsApp.

Only the protected Zahlmeister default payment-request text can use this shared approved WhatsApp template. If a collection uses a custom message text or disables the payment link, internal WhatsApp is skipped and the normal channel-priority fallback continues. This prevents a custom user message from being silently replaced with a different Meta-approved template.

The QR image is not attached to this text template; the payment link is included in the approved template. Email can still include the generated payment QR as an attachment.

## Ponto Connect (optional automatic BankSync)

Use **Ponto Connect** with Ponto's customer-paying model so the connected customer pays Ponto directly. Zahlmeister does not resell BankSync usage. The Ponto client id, client secret and mTLS certificate belong to the Zahlmeister installation. Individual customers authorize their own Ponto organization and selected bank accounts through OAuth; they never enter Ponto API credentials in Zahlmeister.

The current integration targets Ponto Connect API v2 and uses:

- OAuth authorization code with PKCE/S256
- installation client id/client secret
- mTLS for token and API calls
- `offline_access ai name`
- encrypted access/refresh token storage
- one-time refresh-token rotation under a database row lock
- paginated account and transaction reads

### Sandbox

- Sandbox authorization: `https://sandbox-authorization.myponto.com/oauth2/auth`
- Live authorization: `https://authorization.myponto.com/oauth2/auth`

Development defaults to `PONTO_CONNECT_ENVIRONMENT=sandbox`. Production rejects configured sandbox Ponto credentials.

Local sandbox setup:

1. Create a sandbox application in the Ibanity developer portal and enable Ponto Connect Account Information.
2. Register `http://localhost:8003/api/v1/bank-sync/ponto/callback`, or use an HTTPS development hostname and set exactly the same value through `OAUTH_CALLBACK_BASE_URL` if required by the portal.
3. Put `PONTO_CONNECT_CLIENT_ID`, `PONTO_CONNECT_CLIENT_SECRET` and an optional encrypted-key password in ignored `docker/.env`.
4. Store the sandbox mTLS certificate/key as `docker/secrets/ponto/client.crt` and `client.key`.
5. Keep `PONTO_CONNECT_AUTHORIZE_URL` empty in development so the environment selects the official sandbox URL.
6. Connect Ponto in Zahlmeister, authorize sandbox accounts and run a sync.

`GET /api/v1/bank-sync/ponto/configuration` is an authenticated diagnostic endpoint that reports only readiness, environment, callback URI and missing configuration names. It never exposes secrets or tokens.

The worker periodically fetches fresh Ponto data for connected accounts, and users can also request a sync explicitly. Only an exact payment reference plus matching amount/currency is applied automatically; ambiguous candidates remain for review. Accounts that are no longer returned by the authorized Ponto integration are removed from the active local account list while historical bank transactions remain preserved.

Disconnecting Ponto first revokes the remote refresh token through the Ponto OAuth revoke endpoint using mTLS and client authentication. Local tokens/accounts are removed only after that remote revoke succeeds. This prevents a locally deleted connection from remaining active or billable at Ponto.

### Moving Ponto to live

Use a separate live Ponto application, register the production HTTPS callback, replace all sandbox credentials/certificates with live material, set `PONTO_CONNECT_ENVIRONMENT=live` and reconnect customers. Never reuse sandbox tokens in production.

## OAuth callback base

`PUBLIC_APP_URL` is the public frontend URL and is not implicitly the production OAuth callback configuration. Set `OAUTH_CALLBACK_BASE_URL` explicitly in production to the public base that routes `/api/v1/.../callback` to the FastAPI backend. Development may use the direct backend base such as `http://localhost:8003`.

## Mollie Connect (optional online payments)

Online payments use **Mollie Connect**. Each Zahlmeister customer connects their own Mollie account through OAuth. The payment belongs to that merchant and Mollie charges processing fees to that merchant; Zahlmeister does not hold customer funds.

1. Register a Mollie OAuth app.
2. Register `https://<APP_HOST>/api/v1/online-payments/mollie/oauth/callback`.
3. Configure the client id/secret in ignored `docker/.env`.
4. Default scopes are `organizations.read profiles.read payments.read payments.write`.
5. Customers connect their Mollie account and, when needed, select a payment profile.

Provider tokens are encrypted with `APP_SECRET`. `MOLLIE_TEST_MODE=true` can be used for test payments where supported.

## Customer API

The customer API is disabled per organization by default. Customers can enable it under **API & integrations**, create scoped credentials and call `/api/public/v1` with a Bearer API key. Raw keys are returned once and only hashes are persisted. The API uses the same business rules and tenant isolation as the Next.js/Capacitor clients.
