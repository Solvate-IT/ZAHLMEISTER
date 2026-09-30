"""Readiness with several worker processes, and bounded blocking work."""
import asyncio
import time
from datetime import UTC, datetime

import pytest

from app.api.routes import health
from app.core.config import settings
from app.services import blocking


def test_readiness_counts_every_worker_process_heartbeat() -> None:
    condition = str(health._worker_heartbeats().compile(compile_kwargs={"literal_binds": True}))
    # Named per process ("worker:<host>:<pid>"), plus the pre-scaling single name.
    assert "runtime_heartbeats.name = 'worker'" in condition
    assert "runtime_heartbeats.name LIKE 'worker:%'" in condition


@pytest.mark.asyncio
async def test_readiness_uses_the_newest_worker_heartbeat(monkeypatch) -> None:
    now = datetime.now(UTC)

    class Session:
        calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def scalar(self, _statement):
            Session.calls += 1
            return now if Session.calls == 1 else 3

    monkeypatch.setattr(health, "SessionLocal", Session)
    status, age, alive = await health._worker_state()
    assert status == "ok" and age < settings.worker_stale_seconds and alive == 3


@pytest.mark.asyncio
async def test_blocking_work_runs_in_threads_with_bounded_concurrency(monkeypatch) -> None:
    monkeypatch.setattr(settings, "blocking_task_concurrency", 2)
    running = 0
    peak = 0

    def heavy() -> None:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        time.sleep(0.05)
        running -= 1

    started = time.monotonic()
    await asyncio.gather(*(blocking.run_blocking(heavy) for _ in range(6)))
    assert peak == 2
    # Six 50 ms tasks two at a time: about 150 ms, and the event loop stayed free.
    assert time.monotonic() - started < 1.0
