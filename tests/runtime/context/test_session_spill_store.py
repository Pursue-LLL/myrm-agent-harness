"""Unit tests for session-scoped tool output spill store and bounded preview locator harness."""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context.session_spill_store import (
    SessionScopedToolOutputSpillStore,
)
from myrm_agent_harness.runtime.context.session_spill_store_types import (
    SpillPolicy,
    SpillSliceRequest,
)


@pytest.fixture
def spill_store(tmp_path: pytest.TempPathFactory) -> SessionScopedToolOutputSpillStore:
    temp_dir = str(tmp_path)
    policy = SpillPolicy(
        max_inline_bytes=1000,
        max_inline_tokens=250,
        preview_head_lines=5,
        preview_tail_lines=5,
        base_storage_dir=temp_dir,
    )
    return SessionScopedToolOutputSpillStore(default_policy=policy)


def test_tool_output_within_inline_budget_no_spill(
    spill_store: SessionScopedToolOutputSpillStore,
) -> None:
    """Validate that normal small tool outputs stay inline without triggering spill."""
    small_text = "status: ok\nrecords_processed: 42\nelapsed_ms: 12"
    res = spill_store.process_tool_output(
        session_id="sess_normal",
        tool_name="status_probe",
        raw_output=small_text,
    )

    assert not res.is_spilled
    assert res.content == small_text
    assert res.record is None
    assert res.bytes_saved == 0


def test_oversized_tool_output_triggers_spill_and_bounded_preview(
    spill_store: SessionScopedToolOutputSpillStore,
) -> None:
    """Validate that oversized outputs are spilled, persisted, and replaced by bounded preview with locator."""
    # Build 100 lines of verbose logs (~3000 bytes, exceeding 1000 bytes limit)
    lines = [f"LOG_LINE_{i:04d}: operation executing successfully with payload {i * 7}" for i in range(1, 101)]
    large_output = "\n".join(lines)

    res = spill_store.process_tool_output(
        session_id="sess_large",
        tool_name="bash_exec",
        raw_output=large_output,
    )

    assert res.is_spilled
    assert res.record is not None
    assert res.record.session_id == "sess_large"
    assert res.record.total_lines == 100
    assert res.record.locator_uri.startswith("spill://session/sess_large/spill_")
    assert res.bytes_saved > 0

    # Validate preview content structure
    assert "[Output spilled to protect context budget:" in res.content
    assert res.record.locator_uri in res.content
    assert "--- HEAD PREVIEW (First 5 lines) ---" in res.content
    assert "LOG_LINE_0001:" in res.content
    assert "LOG_LINE_0005:" in res.content
    assert "... [90 lines omitted; total 100 lines] ..." in res.content
    assert "--- TAIL PREVIEW (Last 5 lines) ---" in res.content
    assert "LOG_LINE_0100:" in res.content


def test_read_spill_slice_on_demand(
    spill_store: SessionScopedToolOutputSpillStore,
) -> None:
    """Validate on-demand line slicing using canonical spill locator."""
    lines = [f"LINE_{i:03d}: payload log entry detailed" for i in range(1, 51)]
    large_output = "\n".join(lines)

    res = spill_store.process_tool_output(
        session_id="sess_slice",
        tool_name="cat_large",
        raw_output=large_output,
    )
    assert res.is_spilled
    locator = res.record.locator_uri if res.record else ""

    # Request slice from line 20 to 25
    slice_req = SpillSliceRequest(
        locator_uri=locator,
        start_line=20,
        end_line=25,
    )
    slice_res = spill_store.read_spill_slice(slice_req)

    assert slice_res.total_lines == 50
    assert slice_res.lines_returned == 6
    assert "Lines 20-25 of 50" in slice_res.content
    assert "LINE_020" in slice_res.content
    assert "LINE_025" in slice_res.content
    assert "LINE_001" not in slice_res.content


def test_read_spill_slice_invalid_locator_raises_key_error(
    spill_store: SessionScopedToolOutputSpillStore,
) -> None:
    """Validate that attempting to slice non-existent spill raises KeyError."""
    req = SpillSliceRequest(
        locator_uri="spill://session/sess_unknown/spill_missing",
        start_line=1,
        end_line=10,
    )
    with pytest.raises(KeyError):
        spill_store.read_spill_slice(req)


def test_cleanup_session_spills(
    spill_store: SessionScopedToolOutputSpillStore,
) -> None:
    """Validate purging of session-scoped spills upon session termination."""
    lines = [f"ITEM_{i:03d}: verbose telemetry payload" for i in range(100)]
    output_text = "\n".join(lines)

    res1 = spill_store.process_tool_output("sess_cleanup_a", "tool_1", output_text)
    res2 = spill_store.process_tool_output("sess_cleanup_a", "tool_2", output_text)
    res3 = spill_store.process_tool_output("sess_cleanup_b", "tool_3", output_text)

    assert res1.is_spilled and res2.is_spilled and res3.is_spilled

    # Purge session A
    purged_count = spill_store.cleanup_session_spills("sess_cleanup_a")
    assert purged_count == 2

    # Verify session A locators no longer exist
    if res1.record:
        with pytest.raises(KeyError):
            spill_store.read_spill_slice(SpillSliceRequest(locator_uri=res1.record.locator_uri, start_line=1, end_line=5))

    # Verify session B still exists
    if res3.record:
        slice_b = spill_store.read_spill_slice(SpillSliceRequest(locator_uri=res3.record.locator_uri, start_line=1, end_line=5))
        assert slice_b.lines_returned == 5
