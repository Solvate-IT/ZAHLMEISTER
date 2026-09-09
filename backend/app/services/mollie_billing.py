"""Compatibility facade for the Mollie billing implementation.

Provider primitives and legacy compatibility live in ``mollie_billing_core``.
The production reconciliation/renewal entry points are overridden by
``mollie_billing_runtime`` so every recurring charge uses the cancellation-safe
orchestration path.
"""
from app.services import mollie_billing_core as _core

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

from app.services.mollie_billing_runtime import run_billing_cycle, sync_subscription  # noqa: E402,F401
