"""Compatibility facade for the Mollie billing implementation.

Provider primitives and legacy compatibility live in ``mollie_billing_core``.
The production reconciliation/renewal entry points are overridden by
``mollie_billing_runtime`` so every recurring charge uses the cancellation-safe
orchestration path.
"""
from sqlalchemy import select

from app.models.entities import Organization
from app.services import mollie_billing_core as _core

_original_mollie_row = _core._mollie_row


async def _mollie_row(session, organization_id, *, lock: bool = False):
    """Use one canonical lock order for all financial subscription mutations.

    Organization serializes cross-provider entitlement changes. The Mollie
    subscription is then locked before cycle/payment/invoice rows.
    """
    if lock:
        organization = await session.scalar(
            select(Organization.id)
            .where(Organization.id == organization_id)
            .with_for_update()
        )
        if organization is None:
            return None
    return await _original_mollie_row(session, organization_id, lock=lock)


# Core functions resolve this module global at execution time. Replacing it here
# keeps legacy/provider primitives compatible while enforcing the same lock order
# in checkout, webhook reconciliation, cancellation and worker renewals.
_core._mollie_row = _mollie_row

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)
globals()["_mollie_row"] = _mollie_row

from app.services.mollie_billing_runtime import run_billing_cycle, sync_subscription  # noqa: E402,F401
