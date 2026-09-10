# Zahlmeister Pro billing

## Scope

Zahlmeister web Pro billing is platform billing and is intentionally separate from Mollie Connect used by customer organizations to collect participant payments.

The current web tariff is versioned in `backend/app/core/billing_catalog.py`. Price, currency and interval are not environment settings.

## Mollie lifecycle

Zahlmeister Pro billing uses one profile-bound Mollie Standard API Key for the platform account. All Mollie API requests use that key as a Bearer credential. The billing flow uses Mollie Customers, Payments, Mandates and Sales Invoices; it does not create Mollie Subscriptions.

1. The customer completes a Zahlmeister billing profile before checkout.
2. Zahlmeister calculates the tax treatment before starting a payment.
3. Zahlmeister creates a Mollie Customer and a first Payment with `sequenceType=first`.
4. After Mollie verifies the Payment as paid, Zahlmeister stores the valid mandate, activates the paid annual Pro period and creates the immutable local invoice record.
5. Zahlmeister creates a Mollie Sales Invoice with `status=paid` and manual payment details as the receipt for that already verified Payment. The Sales Invoice never initiates a second charge.
6. At the next annual boundary Zahlmeister creates a recurring Mollie Payment with `sequenceType=recurring`, the stored `customerId` and `mandateId`.
7. Only after that recurring Payment is verified as paid does Zahlmeister extend Pro by one year and create the corresponding paid Sales Invoice receipt.
8. Failed, expired or still-pending renewal Payments keep access only within the bounded grace period anchored to the previous paid-through boundary.

Existing installations may still contain legacy Mollie `sub_...` subscriptions created by older Zahlmeister versions. The current purchase path never creates another Mollie Subscription.

## Price stability

The first successful web purchase stores the agreed amount, currency and tariff version in the encrypted Mollie subscription verification data. Future automatic renewals use those stored commercial terms, not the then-current public catalog price.

This means changing `PRO_YEARLY_TARIFF` does not silently raise the price for existing Mollie subscribers. A future price migration must be an explicit product/business process with appropriate customer communication and a deliberate update of the subscription terms. Tax treatment is intentionally recalculated for each future billing period because the billing profile, VAT validation or tax rules may legitimately change.

Each `BillingInvoice` also snapshots the exact tariff version, gross amount, currency, VAT rate, VAT scheme, tax treatment and recipient data used for that period, so later changes never rewrite historical billing evidence.

## Invoice state, recovery and idempotency

`billing_invoices` stores one billing-period record per organization/provider/product/period start. A database unique constraint prevents duplicate local annual periods.

Remote invoice creation follows a local-first/outbox-style flow: the local invoice is committed before the worker is allowed to perform the external Sales Invoice POST. This prevents a process failure after Mollie accepted the request from erasing the local recovery record.

Every local invoice has a stable UUID idempotency key, but Mollie's idempotency retention is time-bounded and therefore is only an additional safeguard. Before any unbound local invoice is POSTed, Zahlmeister first scans the Mollie Sales Invoice list for the stable `ZM:<local billing invoice UUID>` memo reference. It follows Mollie pagination and verifies the organization recipient identifier, environment, VAT scheme, recipient, currency, amount and VAT rate before binding a recovered invoice. If recovery cannot be completed safely, creation fails closed instead of risking a duplicate invoice.

Mollie invoice status values are normalized internally (`payment_reversed` and `payment-reversed`, `canceled` and `cancelled`) before they affect synchronization state.

## Cancellation

Cancelling Pro disables future automatic renewals. A locally reserved renewal for which no Mollie Payment exists yet is marked cancelled and cannot later be charged. If a recurring Mollie Payment has already been created, it is treated as an in-flight financial transaction and may still complete; Zahlmeister does not claim that disabling future renewal reverses an already-created provider payment. A successfully paid period is never revoked by cancellation.

## Webhook verification

The classic Payment webhook remains at `/api/v1/billing/mollie/webhook`. Its payload is never trusted as authoritative payment state: Zahlmeister reads the referenced Payment again from Mollie with the configured API key before applying billing state.

The Sales Invoice webhook accepts the currently supported Sales Invoice event forms. Its HMAC-SHA256 signature is verified against the raw request body using the configured Sales Invoice webhook secret. After extracting the remote invoice ID, Zahlmeister performs an authenticated `GET /sales-invoices/{id}` and applies only the verified Mollie response.

An unknown remote invoice may bind to a local unbound invoice only when its stable `ZM:<UUID>` reference and the financial/account identity checks match exactly. Otherwise it cannot grant Pro.

## Mollie configuration

Platform billing requires one Mollie Standard API Key bound to the Zahlmeister Mollie profile:

- development/test: `MOLLIE_BILLING_API_KEY=test_...`
- production/live: `MOLLIE_BILLING_API_KEY=live_...` or `MOLLIE_BILLING_API_KEY_FILE`

Do not configure or send a separate `profileId` for platform billing. The Standard API Key is already bound to its Mollie profile. `MOLLIE_OAUTH_CLIENT_ID` and `MOLLIE_OAUTH_CLIENT_SECRET` belong only to the separate Mollie Connect integration used when Zahlmeister customers connect their own Mollie accounts; they are not used for Zahlmeister's Pro billing.

Before enabling live Zahlmeister Pro billing:

- activate Invoicing in the platform Mollie account;
- configure the seller/legal and VAT information required by Mollie;
- configure OSS in Mollie before Zahlmeister sends `vatScheme=one-stop-shop` for EU consumer invoices;
- configure a live Standard API Key;
- create a strong Sales Invoice webhook secret;
- configure the next-generation Mollie Sales Invoice webhook at `https://<APP_HOST>/api/v1/billing/mollie/invoice-webhook`;
- store the same webhook secret in `MOLLIE_BILLING_WEBHOOK_SECRET_FILE` in production.

`docker/scripts/generate-secrets.sh` creates `mollie_billing_webhook_secret` without rotating existing production secrets. The Mollie API key remains an externally supplied secret and must be stored separately as `mollie_billing_api_key` when billing is enabled.

## Tax policy

Tax decisions are deliberately kept outside the Mollie transport layer. Mollie receives the tax decision and creates the invoice; it is not used as Zahlmeister's tax engine.

The versioned policy in `backend/app/core/tax_catalog.py` currently supports EU digital SaaS billing for an Austrian seller:

- Austrian customers: Austrian standard VAT;
- EU consumers outside Austria: destination-country standard VAT with OSS;
- EU businesses outside Austria: reverse charge only after the VAT number has been successfully validated through VIES.

If VIES is unavailable, Zahlmeister does not silently grant reverse charge. Checkout or renewal is retried later instead of creating a potentially incorrect tax-free invoice.

Non-EU billing profiles can already be stored using ISO country codes, but automatic charging is deliberately blocked until an explicit tax rule/provider covers that jurisdiction. Zahlmeister must never infer `0%` merely because a customer is outside the EU.

## Billing profile and UI transparency

Business billing profiles require a legal organization name and at least one VAT number or organization/registry number already at API validation time. EU B2B reverse charge still additionally requires a valid VIES VAT number.

The billing UI shows the current provider/status, auto-renew setting, paid-through date, invoices, billing periods, gross amount, VAT rate and payment status. For Mollie renewal it also shows the subscriber's actual stored annual amount and next renewal date rather than blindly showing the current catalog price.

Billing/profile/invoice/renewal/cancellation copy is available for all supported Zahlmeister UI languages. English remains the final fallback only for an unknown/unsupported locale.

## Database migrations

Production schema changes are managed with Alembic. `python -m app.db.bootstrap` runs `upgrade head` and then Alembic's schema-drift check. Every schema change after the compatibility baseline must be implemented as an explicit Alembic revision.

The nullable legacy `billing_legal_entities.mollie_profile_id` column is retained for schema compatibility but is no longer populated or used by the billing provider. It can be removed later in a dedicated production-safe migration if desired.

## Worker behavior

The existing PostgreSQL-backed worker performs periodic billing recovery. It does not introduce Redis, a broker or a second billing service. Pending Payments, due renewals and open local Mollie invoice receipts are reconciled independently so one provider or validation failure cannot stop unrelated organizations.
