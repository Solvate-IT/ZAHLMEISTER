# Zahlmeister Pro billing

## Scope

Zahlmeister web Pro billing is platform billing and is intentionally separate from Mollie Connect used by customer organizations to collect participant payments.

The current web tariff is versioned in `backend/app/core/billing_catalog.py`. Price, currency and interval are not environment settings.

## Mollie lifecycle

New web Pro purchases use Mollie Customers, Payments, Mandates and Sales Invoices. They do not create a new Mollie Subscription.

1. The customer completes a Zahlmeister billing profile before checkout.
2. Zahlmeister calculates the tax treatment before starting a payment.
3. A first Mollie customer payment with `sequenceType=first` establishes a mandate.
4. After Mollie verifies that payment as paid, Zahlmeister activates the paid annual Pro period and stores the local annual invoice record.
5. A later worker pass creates the Mollie Sales Invoice for that already-paid period using the manual-payment receipt flow.
6. At the end of the paid period, Zahlmeister first stores the next local annual invoice and immediately enters the bounded renewal grace period.
7. A later worker pass creates the Mollie Sales Invoice using the existing `customerId` and `mandateId` so Mollie performs the automatic mandate payment.
8. While Mollie reports `pending-payment`, and when an automatic payment falls back to `issued`, `overdue` or `payment-reversed`, Pro remains available only within the same bounded seven-day grace period anchored to the previous paid-through boundary.
9. A paid renewal extends Pro by exactly one year from the previous paid-through boundary and clears the grace state.

Existing installations may still contain legacy Mollie `sub_...` subscriptions created by older Zahlmeister versions. Those rows continue to be reconciled and can be cancelled. The new purchase path never creates another Mollie Subscription.

## Price stability

The first successful web purchase stores the agreed amount, currency and tariff version in the encrypted Mollie subscription verification data. Future automatic renewals use those stored commercial terms, not the then-current public catalog price.

This means changing `PRO_YEARLY_TARIFF` does not silently raise the price for existing Mollie subscribers. A future price migration must be an explicit product/business process with appropriate customer communication and a deliberate update of the subscription terms. Tax treatment is intentionally recalculated for each future billing period because the billing profile, VAT validation or tax rules may legitimately change.

Each `BillingInvoice` also snapshots the exact tariff version, gross amount, currency, VAT rate, VAT scheme, tax treatment and recipient data used for that period, so later changes never rewrite historical billing evidence.

## Invoice state, recovery and idempotency

`billing_invoices` stores one billing-period record per organization/provider/product/period start. A database unique constraint prevents duplicate local annual periods.

Remote invoice creation follows a local-first/outbox-style flow: the local invoice is committed before the worker is allowed to perform the external Sales Invoice POST. This prevents a process failure after Mollie accepted the request from erasing the local recovery record.

Every local invoice has a stable UUID idempotency key, but Mollie's idempotency retention is time-bounded and therefore is only an additional safeguard. Before any unbound local invoice is POSTed, Zahlmeister first scans the Mollie Sales Invoice list for the stable `ZM:<local billing invoice UUID>` memo reference. It follows Mollie pagination and verifies the organization recipient identifier, environment, VAT scheme, recipient, currency, amount and VAT rate before binding a recovered invoice. If recovery cannot be completed safely, creation fails closed instead of risking a duplicate invoice or double charge.

This recovery is not limited by the age of the local invoice. A long worker outage therefore does not create the previous one-hour dead zone: after restart, Zahlmeister can recover a remotely created invoice before deciding whether a new POST is safe.

Mollie invoice status values are normalized internally (`payment_reversed` and `payment-reversed`, `canceled` and `cancelled`) before they affect entitlement or UI state.

## Cancellation

Cancellation always disables future automatic renewal in Zahlmeister first within the same database transaction.

For the new Sales Invoice flow:

- a staged local renewal that has not yet been created at Mollie is marked cancelled and will never be POSTed;
- if the remote invoice is missing locally, Zahlmeister first performs the same exhaustive recovery scan before deciding that no remote invoice exists;
- an open remote renewal invoice is refreshed from Mollie and cancelled through the Sales Invoice API when cancellation is allowed;
- a renewal that is already paid is not undone: the customer keeps the paid Pro period, but `auto_renew` remains disabled for the following year;
- `pending-payment` means Mollie has already initiated the asynchronous mandate payment. The UI explicitly states that cancelling at that point stops future renewals but cannot promise that an already-running annual charge will be stopped. If that payment succeeds, the paid period remains active with `auto_renew=false`. If it fails and the invoice returns to an open state, the open invoice is cancelled rather than being left as a future payable renewal.

Legacy Mollie `sub_...` subscriptions continue to use Mollie's subscription cancellation endpoint and remain backward compatible.

## Webhook verification

The Sales Invoice webhook accepts both forms currently documented by Mollie: the direct Sales Invoice entity snapshot and the generic next-generation `event` envelope carrying a `sales-invoice.*` event and `entityId` (or embedded entity).

The HMAC-SHA256 signature is verified against the raw request body using the configured Sales Invoice webhook secret. The webhook body is never trusted as authoritative billing state. After extracting the remote invoice ID, Zahlmeister performs an authenticated `GET /sales-invoices/{id}` and applies only that verified Mollie response.

An unknown remote invoice may bind to a local unbound invoice only when its stable `ZM:<UUID>` reference and the financial/account identity checks match exactly. Otherwise it cannot grant Pro.

## Mollie configuration

Before enabling live Zahlmeister Pro billing:

- activate Invoicing in the platform Mollie account;
- configure the seller/legal and VAT information required by Mollie;
- configure OSS in Mollie before Zahlmeister sends `vatScheme=one-stop-shop` for EU consumer invoices;
- use a live Mollie API key;
- create a strong Sales Invoice webhook secret;
- configure the next-generation Mollie Sales Invoice webhook at:
  `https://<APP_HOST>/api/v1/billing/mollie/invoice-webhook`;
- store the same webhook secret in `MOLLIE_BILLING_WEBHOOK_SECRET_FILE` in production.

`docker/scripts/generate-secrets.sh` creates `mollie_billing_webhook_secret` without rotating existing production secrets. If a missing `database_url` has to be generated while `postgres_password` already exists, the script derives the URL from the existing password so the two secrets cannot diverge. The Mollie API key remains an externally supplied secret and must be stored separately as `mollie_billing_api_key` when billing is enabled.

The classic payment webhook remains at `/api/v1/billing/mollie/webhook` for the first mandate-establishing payment. Sales Invoice status events use the signed `/api/v1/billing/mollie/invoice-webhook` endpoint.

## Tax policy

Tax decisions are deliberately kept outside the Mollie transport layer. Mollie receives the tax decision and creates the invoice; it is not used as Zahlmeister's tax engine.

The versioned policy in `backend/app/core/tax_catalog.py` currently supports EU digital SaaS billing for an Austrian seller:

- Austrian customers: Austrian standard VAT;
- EU consumers outside Austria: destination-country standard VAT with OSS;
- EU businesses outside Austria: reverse charge only after the VAT number has been successfully validated through VIES.

If VIES is unavailable, Zahlmeister does not silently grant reverse charge. Checkout or renewal is retried later instead of creating a potentially incorrect tax-free invoice.

Non-EU billing profiles can already be stored using ISO country codes, but automatic charging is deliberately blocked until an explicit tax rule/provider covers that jurisdiction. Zahlmeister must never infer `0%` merely because a customer is outside the EU. This keeps the data model globally usable without pretending that worldwide VAT/GST/sales-tax compliance has already been implemented.

Future non-EU support should extend the tax-decision abstraction or connect a suitable tax provider. It must retain the same per-invoice tax snapshot so later rule changes cannot rewrite historical billing periods.

## Billing profile and UI transparency

Business billing profiles require a legal organization name and at least one VAT number or organization/registry number already at API validation time. EU B2B reverse charge still additionally requires a valid VIES VAT number.

The billing UI shows the current provider/status, auto-renew setting, paid-through date, invoices, billing periods, gross amount, VAT rate and payment status. For Mollie renewal it also shows the subscriber's actual stored annual amount and next renewal date rather than blindly showing the current catalog price. The purchase and renewal copy explicitly states that the displayed annual price includes applicable VAT and that the agreed annual amount is collected automatically through the Mollie mandate until renewal is cancelled.

Billing/profile/invoice/renewal/cancellation copy is available for all 24 supported Zahlmeister UI languages. English remains the final fallback only for an unknown/unsupported locale.

## Database migrations

Production schema changes are managed with Alembic. `python -m app.db.bootstrap` now runs `upgrade head` and then Alembic's schema-drift check. The existing production `bootstrap` container therefore applies migrations before backend and worker startup and refuses to start the application when model metadata and the migrated schema do not match.

Revision `0001_current_schema_baseline` is a one-time compatibility baseline for installations created before Alembic was introduced. It only creates missing tables/indexes from the current metadata and adopts the existing schema into Alembic. It deliberately does not attempt destructive guesses about unknown production data. The immediate drift check blocks an installation whose existing tables differ from the expected schema so it can be reconciled explicitly. Every schema change after the baseline must be implemented as a normal explicit Alembic revision.

## Worker behavior

The existing PostgreSQL-backed worker performs the periodic billing recovery scan. It does not introduce Redis, a broker or a second billing service.

The billing scan runs every ten minutes and selects only organizations that require action: pending first payments, grace-period subscriptions, renewals whose paid-through date has been reached, or local Mollie invoices with an open status. Failures are isolated per organization so one invalid billing profile, temporary VIES failure or Mollie outage cannot stop unrelated renewals.
