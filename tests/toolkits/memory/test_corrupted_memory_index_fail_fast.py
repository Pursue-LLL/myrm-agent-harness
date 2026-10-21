"""Tests for CorruptedMemoryIndexFailFast.

[INPUT]
myrm_agent_harness.toolkits.memory.relational (POS: SQLite relational store & exceptions)
myrm_agent_harness.toolkits.memory.reliability (POS: probe result contracts)

[OUTPUT]
Unit tests covering fail-fast corruption detection, reset on poisoned handle,
check_integrity diagnostics, and reliability probe creation.

[POS]
Unit tests for memory index corruption resilience and fail-fast barriers.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.manager import (
    CorruptedMemoryIndexError,
)
from myrm_agent_harness.toolkits.memory.relational.sqlite_store import SQLiteRelationalStore
from myrm_agent_harness.toolkits.memory.reliability import (
    create_corrupted_index_probe_result,
)


@pytest.mark.asyncio
async def test_sqlite_store_healthy_integrity_and_quick_check() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "healthy_relational.db")
        store = SQLiteRelationalStore(db_path)

        # Basic operations succeed
        await store.set_profile("theme", "dark")
        val = await store.get_profile("theme")
        assert val == "dark"

        # Assert integrity passes
        await store.assert_store_integrity()

        # check_integrity passes
        is_ok, msg = await store.check_integrity()
        assert is_ok is True
        assert msg == "ok"

        await store.close()


@pytest.mark.asyncio
async def test_sqlite_store_corrupted_header_raises_fail_fast() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "corrupted_relational.db")
        store = SQLiteRelationalStore(db_path)
        await store.set_profile("key1", "val1")
        await store.close()

        # Intentionally corrupt the SQLite file header / payload
        with open(db_path, "r+b") as f:
            f.seek(16)  # SQLite page size / file header offset
            f.write(b"\xff\xff\xff\xff\x00\x00\x00\x00corrupt_payload_xyz")

        corrupt_store = SQLiteRelationalStore(db_path)

        with pytest.raises(CorruptedMemoryIndexError) as exc_info:
            await corrupt_store.get_profile("key1")

        err = exc_info.value
        assert err.db_path == str(Path(db_path).resolve())
        assert err.index_type == "sqlite_relational"
        assert corrupt_store._connection is None  # Poisoned handle is reset to None

        # check_integrity on corrupted file returns False
        is_ok, msg = await corrupt_store.check_integrity()
        assert is_ok is False
        assert "error" in msg.lower() or "failed" in msg.lower()

        await corrupt_store.close()


@pytest.mark.asyncio
async def test_integrity_check_ignores_fts_staleness_caused_by_a_concurrent_writer() -> None:
    """A second connection committing FTS5 rows must not make a healthy store look corrupted."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "shared.db")
        writer = SQLiteRelationalStore(db_path)
        checker = SQLiteRelationalStore(db_path)
        await checker.set_profile("warm", "up")
        await writer.record_exact_fact(memory_id="m0", user_id="u", content="seed", identifiers=["00000000"])
        await checker.assert_store_integrity()

        async def _write() -> None:
            for i in range(120):
                await writer.record_exact_fact(
                    memory_id=f"m{i % 6}", user_id="u", content=f"fact {i} works at", identifiers=[f"{i:08x}"]
                )

        async def _check() -> None:
            for _ in range(120):
                await checker.assert_store_integrity()
                await asyncio.sleep(0)

        await asyncio.gather(_write(), _check())

        await writer.close()
        await checker.close()


def test_create_corrupted_index_probe_result() -> None:
    probe = create_corrupted_index_probe_result(
        "/data/memory.db",
        "database disk image is malformed",
        index_type="sqlite_relational",
        repair_suggestion="Restore from backup snapshot",
    )

    assert probe.status == "critical"
    assert probe.category == "index"
    assert probe.safe_to_retry is False
    assert len(probe.repair_plans) == 1
    assert probe.repair_plans[0].id == "repair_corrupt_sqlite_relational"
    assert probe.repair_plans[0].executable is True
    assert "database disk image is malformed" in probe.evidence
