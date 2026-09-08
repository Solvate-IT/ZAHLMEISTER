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

## Invoice state and idempotency

`billing_invoices` stores one immutable billing-period record per organization/provider/product/period start. It snapshots the tariff version, amount, currency, VAT rate, VAT scheme, tax treatment and relevant recipient information used for that period.

Remote invoice creation follows a local-first/outbox-style flow: the local invoice is committed before the worker is allowed to perform the external Sales Invoice POST. This prevents a process failure after Mollie accepted the request from erasing the local recovery record.

Every local invoice has a stable UUID idempotency key. Mollie's idempotency retention is time-bounded, so Zahlmeister does not rely on that key indefinitely. Automatic create retries are allowed only after a short local-first delay and for at most 55 minutes from the local invoice creation time. The billing worker runs every ten minutes so several retries are possible while the key is still within the safe window. Once that window has passed, an unbound invoice is never blindly POSTed again.

Every newly created Mollie invoice also carries `ZM:<local billing invoice UUID>` on its memo. If the Mollie request succeeded but its HTTP response was lost, a signed Sales Invoice webhook can therefore recover the exact local row. Zahlmeister then performs an authenticated Mollie GET and verifies the local reference, organization recipient identifier, environment, VAT scheme, recipient, amount, VAT rate and creation window before binding the remote invoice. An unsolicited or ambiguous invoice cannot grant Pro.

Mollie Sales Invoice statuses are synchronized both through the signed next-generation webhook and by the worker. The worker is the recovery path when a webhook is delayed or lost.

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

If VIES is unavailable, Zahlmeister does not silently grant reverse charge. The checkout/renewal is retried later instead of creating a potentially incorrect tax-free invoice.

Non-EU billing profiles can already be stored using ISO country codes, but automatic charging is deliberately blocked until an explicit tax rule/provider covers that jurisdiction. Zahlmeister must never infer `0%` merely because a customer is outside the EU. This keeps the data model globally usable without pretending that worldwide VAT/GST/sales-tax compliance has already been implemented.

Future non-EU support should extend the tax-decision abstraction or connect a suitable tax provider. It must retain the same per-invoice tax snapshot so later rule changes cannot rewrite historical billing periods.

## Data model

`BillingProfile` contains the current invoice recipient details of an organization. Changes affect future invoices only.

`BillingInvoice` is historical billing evidence. Its recipient/tax/tariff snapshots are not recalculated after creation.

Both tables reference the organization with cascading deletion, avoiding orphan billing records when an account is deleted.

## Worker behavior

The existing PostgreSQL-backed worker performs the periodic billing recovery scan. It does not introduce Redis, a broker or a second billing service.

The billing scan runs every ten minutes and selects only organizations that require action: pending first payments, grace-period subscriptions, renewals whose paid-through date has been reached, or local Mollie invoices with an open status. Failures are isolated per organization so one invalid billing profile or temporary VIES failure cannot stop unrelated renewals.
