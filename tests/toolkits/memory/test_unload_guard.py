# [POS]: tests/toolkits/memory/test_unload_guard.py
# [INPUT]: pytest, myrm_agent_harness.toolkits.memory.unload_guard
# [OUTPUT]: test_unload_guard suite
"""Unit test suite for desktop/WebUI unload and graceful flush finalize guard.

Validates zero-LLM crash-proof emergency snapshot creation, persistence into
durable handoffs, listing unfinalized sessions, and startup restoration.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.unload_guard import (
    EmergencyFlushRequest,
    EmergencySnapshotReason,
    UnloadGracefulFlushGuard,
    ZeroLlmEmergencySnapshotBuilder,
)


@pytest.fixture
def temp_storage_dir() -> Path:
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


def test_zero_llm_emergency_snapshot_builder() -> None:
    builder = ZeroLlmEmergencySnapshotBuilder()
    req = EmergencyFlushRequest(
        session_id="session-test-01",
        active_goal="Refactor authentication middleware and token validation",
        reason=EmergencySnapshotReason.BROWSER_UNLOAD,
        last_tool_call="run_command(pytest tests/)",
        modified_files=["app/auth.py", "app/routes.py"],
        recent_errors=["Test failed: 401 Unauthorized"],
        next_actions=["Fix JWT expiry logic", "Rerun auth tests"],
    )

    md = builder.build_markdown(request=req, handoff_id="handoff-101")
    assert "Emergency Handoff Memorandum [handoff-101]" in md
    assert "session-test-01" in md
    assert "browser_unload" in md
    assert "Refactor authentication middleware" in md
    assert "run_command(pytest tests/)" in md
    assert "app/auth.py" in md
    assert "Test failed: 401 Unauthorized" in md
    assert "1. Fix JWT expiry logic" in md
    assert "2. Rerun auth tests" in md
    assert "Zero-LLM Crash-Proof Fallback" in md


def test_unload_guard_flush_and_persistence(temp_storage_dir: Path) -> None:
    guard = UnloadGracefulFlushGuard(storage_dir=temp_storage_dir)
    req = EmergencyFlushRequest(
        session_id="session-abrupt-close",
        active_goal="Migrate SQLite schema to version 4",
        reason=EmergencySnapshotReason.WINDOW_CLOSE_REQUESTED,
        modified_files=["migrations/v4.sql"],
        recent_errors=["Database locked"],
        next_actions=["Release write lock and rerun migration"],
    )

    result = guard.flush(req)
    assert result.session_id == "session-abrupt-close"
    assert result.is_zero_llm is True
    assert result.handoff_id.startswith("handoff-")
    assert Path(result.persisted_path).exists()

    # Check content of persisted handoff file
    persisted_text = Path(result.persisted_path).read_text(encoding="utf-8")
    assert "session-abrupt-close" in persisted_text


def test_unload_guard_list_unfinalized_and_acknowledge(temp_storage_dir: Path) -> None:
    guard = UnloadGracefulFlushGuard(storage_dir=temp_storage_dir)

    # 1. Initially no unfinalized
    assert len(guard.list_unfinalized()) == 0

    # 2. Trigger two emergency flushes
    req1 = EmergencyFlushRequest(
        session_id="sess-1",
        active_goal="Compile frontend assets",
        reason=EmergencySnapshotReason.BROWSER_UNLOAD,
    )
    req2 = EmergencyFlushRequest(
        session_id="sess-2",
        active_goal="Run integration benchmarks",
        reason=EmergencySnapshotReason.SESSION_SWITCH,
    )

    res1 = guard.flush(req1)
    res2 = guard.flush(req2)

    # 3. List unfinalized
    unfinalized = guard.list_unfinalized()
    assert len(unfinalized) == 2
    unfinalized_ids = {u.handoff_id for u in unfinalized}
    assert res1.handoff_id in unfinalized_ids
    assert res2.handoff_id in unfinalized_ids

    # 4. Acknowledge/claim first session
    success = guard.acknowledge(res1.handoff_id, claimer_session_id="new-active-session")
    assert success is True

    # 5. Only res2 remains pending
    remaining = guard.list_unfinalized()
    assert len(remaining) == 1
    assert remaining[0].handoff_id == res2.handoff_id
