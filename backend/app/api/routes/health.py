import hmac
from datetime import UTC, datetime

from fastapi import APIRouter, Header, HTTPException, status
from sqlalchemy import func, select, text

from app.core.config import settings
from app.db.session import SessionLocal, engine
from app.models.entities import RuntimeHeartbeat, ScheduledJob
from app.services.mollie_billing import billing_readiness_errors

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _worker_state() -> tuple[str, float | None]:
    async with SessionLocal() as session:
        heartbeat = await session.get(RuntimeHeartbeat, "worker")
    if heartbeat is None:
        return "missing", None
    seen = heartbeat.last_seen_at
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=UTC)
    age = max(0.0, (datetime.now(UTC) - seen).total_seconds())
    return ("ok" if age <= settings.worker_stale_seconds else "stale"), age


@router.get("/ready")
async def ready() -> dict[str, str]:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc

    security_errors = settings.production_security_errors()
    if security_errors:
        raise HTTPException(status_code=503, detail="production configuration is unsafe")

    if settings.mollie_billing_configured:
        billing_errors = billing_readiness_errors()
        if billing_errors:
            raise HTTPException(status_code=503, detail="billing configuration is incomplete")

    if settings.readiness_require_worker:
        worker_status, _ = await _worker_state()
        if worker_status != "ok":
            raise HTTPException(status_code=503, detail="worker unavailable")
    return {"status": "ready"}


@router.get("/health/metrics")
async def operational_metrics(
    x_monitoring_token: str | None = Header(default=None),
) -> dict[str, object]:
    configured = settings.monitoring_token
    if not configured:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if not x_monitoring_token or not hmac.compare_digest(x_monitoring_token, configured):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    now = datetime.now(UTC)
    async with SessionLocal() as session:
        pending = await session.scalar(
            select(func.count()).select_from(ScheduledJob).where(ScheduledJob.status == "pending")
        )
        running = await session.scalar(
            select(func.count()).select_from(ScheduledJob).where(ScheduledJob.status == "running")
        )
        failed = await session.scalar(
            select(func.count()).select_from(ScheduledJob).where(ScheduledJob.status == "failed")
        )
        oldest = await session.scalar(
            select(func.min(ScheduledJob.scheduled_at)).where(ScheduledJob.status == "pending")
        )
    worker_status, worker_age = await _worker_state()
    if oldest is not None and oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=UTC)
    oldest_age = max(0.0, (now - oldest).total_seconds()) if oldest else 0.0
    return {
        "status": "ok" if worker_status == "ok" else "degraded",
        "environment": settings.environment,
        "worker": {
            "status": worker_status,
            "heartbeat_age_seconds": round(worker_age, 2) if worker_age is not None else None,
        },
        "jobs": {
            "pending": int(pending or 0),
            "running": int(running or 0),
            "failed": int(failed or 0),
            "oldest_pending_age_seconds": round(oldest_age, 2),
        },
    }
