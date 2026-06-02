"""Unit tests for engine/integrity.py — verify_chain."""

from __future__ import annotations

from dataclasses import replace as dc_replace
from datetime import UTC, datetime, timedelta

from myrm_agent_harness.toolkits.cron.engine.integrity import (
    GENESIS_HASH,
    compute_integrity_hash,
    verify_chain,
)
from myrm_agent_harness.toolkits.cron.types import CronRunRecord, RunStatus

_NOW = datetime(2026, 3, 29, 12, 0, 0, tzinfo=UTC)


def _run(
    run_id: str,
    job_id: str = "j1",
    offset_min: int = 0,
    prev_hash: str = GENESIS_HASH,
) -> CronRunRecord:
    t = _NOW + timedelta(minutes=offset_min)
    run = CronRunRecord(
        id=run_id,
        job_id=job_id,
        started_at=t,
        finished_at=t + timedelta(seconds=1),
        duration_ms=1000,
        status=RunStatus.OK,
        prev_hash=prev_hash,
    )
    integrity_hash = compute_integrity_hash(run, prev_hash)
    return dc_replace(run, integrity_hash=integrity_hash)


class TestVerifyChain:
    def test_valid_chain(self) -> None:
        r1 = _run("r1", offset_min=0)
        r2 = _run("r2", offset_min=1, prev_hash=r1.integrity_hash or "")
        r3 = _run("r3", offset_min=2, prev_hash=r2.integrity_hash or "")
        breaks = verify_chain([r1, r2, r3])
        assert breaks == []

    def test_tampered_prev_hash(self) -> None:
        r1 = _run("r1", offset_min=0)
        r2 = _run("r2", offset_min=1, prev_hash=r1.integrity_hash or "")
        r2_tampered = dc_replace(r2, prev_hash="tampered")
        breaks = verify_chain([r1, r2_tampered])
        assert len(breaks) >= 1
        assert any(b.kind == "prev_hash_mismatch" for b in breaks)

    def test_tampered_integrity_hash(self) -> None:
        r1 = _run("r1", offset_min=0)
        r1_tampered = dc_replace(r1, integrity_hash="tampered_hash")
        breaks = verify_chain([r1_tampered])
        assert len(breaks) >= 1
        assert any(b.kind == "integrity_hash_mismatch" for b in breaks)

    def test_empty_chain(self) -> None:
        assert verify_chain([]) == []

    def test_stops_at_missing_hash(self) -> None:
        r1 = CronRunRecord(
            id="r1",
            job_id="j1",
            started_at=_NOW,
            finished_at=_NOW + timedelta(seconds=1),
            duration_ms=1000,
            status=RunStatus.OK,
        )
        assert verify_chain([r1]) == []
