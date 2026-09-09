from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.billing import BillingCycle, BillingPaymentTransaction
from app.models.platform import StoreSubscription
from app.services import mollie_billing_core as core


async def _execute_due_renewal(organization_id: UUID) -> bool:
    reserved = await core._reserve_due_renewal(organization_id)
    if reserved is None:
        return False
    cycle_id, tx_id, customer_id, mandate_id = reserved
    await core._valid_mandate(customer_id, mandate_id)

    async with SessionLocal() as session:
        cycle = await session.get(BillingCycle, cycle_id)
        tx = await session.get(BillingPaymentTransaction, tx_id)
        if cycle is None or tx is None:
            raise core.MollieBillingUnavailable("Billing reservation disappeared")
        if tx.provider_reference:
            payment = await core._get_payment(tx.provider_reference)
        else:
            payment = await core._find_remote_payment(tx, cycle, customer_id)

    if payment is None:
        # Serialize the final cancellation check with the charge-producing provider
        # write. Cancellation uses the same StoreSubscription row lock. Whoever
        # obtains the lock first wins: cancellation prevents the POST; an already
        # started payment is durably bound before cancellation can proceed.
        async with SessionLocal.begin() as session:
            row = await core._mollie_row(session, organization_id, lock=True)
            cycle = await session.get(BillingCycle, cycle_id, with_for_update=True)
            tx = await session.get(BillingPaymentTransaction, tx_id, with_for_update=True)
            if row is None or cycle is None or tx is None:
                raise core.MollieBillingUnavailable("Billing reservation disappeared")
            if not row.auto_renew or cycle.status == "cancelled" or tx.status == "cancelled":
                if tx.provider_reference is None:
                    tx.status = "cancelled"
                    cycle.status = "cancelled"
                return False
            if tx.provider_reference:
                existing_reference = tx.provider_reference
                payment = None
            else:
                existing_reference = None
                webhook = core._webhook_url()
                payload: dict[str, Any] = {
                    "amount": {
                        "currency": tx.currency,
                        "value": core._decimal_amount(tx.gross_amount),
                    },
                    "description": "Zahlmeister Pro renewal",
                    "sequenceType": "recurring",
                    "customerId": customer_id,
                    "mandateId": mandate_id,
                    "metadata": core._payment_metadata(organization_id, cycle, tx),
                }
                if webhook:
                    payload["webhookUrl"] = webhook
                payment = await core._request_json(
                    "POST",
                    "payments",
                    json_body=payload,
                    idempotency_key=f"zahlmeister-payment-{tx.idempotency_key}",
                )
                payment_id = payment.get("id")
                if not isinstance(payment_id, str) or not payment_id.startswith("tr_"):
                    raise core.MollieBillingUnavailable("Mollie renewal payment creation failed")
                tx.provider_reference = payment_id
                tx.status = core._remote_payment_status(payment.get("status"))
                tx.last_synced_at = datetime.now(UTC)
                cycle.status = "payment_pending"
        if existing_reference:
            payment = await core._get_payment(existing_reference)
    else:
        payment_id = payment.get("id")
        if not isinstance(payment_id, str) or not payment_id.startswith("tr_"):
            raise core.MollieBillingUnavailable("Recovered Mollie renewal payment is invalid")
        async with SessionLocal.begin() as session:
            row = await core._mollie_row(session, organization_id, lock=True)
            cycle = await session.get(BillingCycle, cycle_id, with_for_update=True)
            tx = await session.get(BillingPaymentTransaction, tx_id, with_for_update=True)
            if row is None or cycle is None or tx is None:
                raise core.MollieBillingUnavailable("Billing reservation disappeared")
            if tx.provider_reference and tx.provider_reference != payment_id:
                raise core.MollieBillingVerificationError("Mollie payment binding changed unexpectedly")
            tx.provider_reference = payment_id
            tx.status = core._remote_payment_status(payment.get("status"))
            tx.last_synced_at = datetime.now(UTC)
            cycle.status = "payment_pending" if tx.status in core.OPEN_PAYMENT_STATUSES else cycle.status

    payment_id = payment.get("id") if isinstance(payment, dict) else None
    if not isinstance(payment_id, str) or not payment_id.startswith("tr_"):
        raise core.MollieBillingUnavailable("Mollie renewal payment reference is invalid")
    await core._process_payment_payload(await core._get_payment(payment_id))
    return True


async def _reconcile_legacy_subscription_safely(
    organization_id: UUID,
    customer_id: str,
    subscription_id: str,
    *,
    cancellation_pending: bool,
) -> None:
    if cancellation_pending:
        # A failed remote cancellation must never resurrect local auto-renew.
        await core._request_json("DELETE", f"customers/{customer_id}/subscriptions/{subscription_id}")
        async with SessionLocal.begin() as session:
            row = await core._mollie_row(session, organization_id, lock=True)
            if row is not None:
                data = core._verification_data(row)
                data.pop("subscription_id", None)
                data.pop("subscription_status", None)
                row.verification_data_encrypted = core.encrypt_config(data)
                row.last_verified_at = datetime.now(UTC)
        return
    await core._reconcile_legacy_subscription(organization_id, customer_id, subscription_id)


async def sync_subscription(_session, organization_id: UUID) -> None:
    core._require_configured()
    async with SessionLocal() as session:
        row = await core._mollie_row(session, organization_id)
        if row is None:
            return
        data = core._verification_data(row)
        legacy_customer = data.get("mollie_customer_id")
        legacy_subscription = data.get("subscription_id")
        cancellation_pending = bool(row.cancelled_at and not row.auto_renew)
        tx_ids = (
            await session.execute(
                select(BillingPaymentTransaction.id)
                .where(
                    BillingPaymentTransaction.organization_id == organization_id,
                    BillingPaymentTransaction.provider == core.MOLLIE_PROVIDER,
                    BillingPaymentTransaction.status.in_(["reserved", "open", "pending"]),
                )
                .order_by(BillingPaymentTransaction.created_at)
            )
        ).scalars().all()

    if isinstance(legacy_customer, str) and isinstance(legacy_subscription, str):
        await _reconcile_legacy_subscription_safely(
            organization_id,
            legacy_customer,
            legacy_subscription,
            cancellation_pending=cancellation_pending,
        )
        return

    for tx_id in tx_ids:
        async with SessionLocal() as session:
            tx = await session.get(BillingPaymentTransaction, tx_id)
            if tx is None:
                continue
            cycle = await session.get(BillingCycle, tx.cycle_id)
            row = await core._mollie_row(session, organization_id)
            if cycle is None or row is None:
                continue
            data = core._verification_data(row)
            customer_id = data.get("mollie_customer_id")
            if not isinstance(customer_id, str):
                continue
            payment = (
                await core._get_payment(tx.provider_reference)
                if tx.provider_reference
                else await core._find_remote_payment(tx, cycle, customer_id)
            )
        if payment is not None:
            await core._process_payment_payload(payment)

    await core._sync_receipts(organization_id)
    await _execute_due_renewal(organization_id)


async def run_billing_cycle(_session) -> dict[str, int]:
    if not core.billing_configured():
        return {"invoices_synced": 0, "renewals_created": 0}
    invoices_synced = await core._sync_receipts()
    async with SessionLocal() as session:
        ids = (
            await session.execute(
                select(StoreSubscription.organization_id)
                .where(
                    StoreSubscription.provider == core.MOLLIE_PROVIDER,
                    StoreSubscription.auto_renew.is_(True),
                    StoreSubscription.status.in_(["active", "grace_period", "expired"]),
                )
                .order_by(StoreSubscription.expires_at)
                .limit(100)
            )
        ).scalars().all()
    renewals = 0
    for organization_id in ids:
        if await _execute_due_renewal(organization_id):
            renewals += 1
    return {"invoices_synced": invoices_synced, "renewals_created": renewals}
