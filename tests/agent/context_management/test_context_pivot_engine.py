"""Tests for Lossless Context Pivot and Scratchpad Reset Suite (Item 209).

Verifies zero-compaction clean context window pivots, structured phase handoff scratchpads,
uncompressed snapshot archival, lossless message restoration, and configurable continuation prompts.
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.context_pivot.context_pivot_engine import (
    LosslessContextPivotEngine,
)
from myrm_agent_harness.agent.context_management.context_pivot.context_pivot_types import (
    ArchivedContextSnapshot,
    ContextPivotConfig,
    ContextPivotResult,
    HandoffScratchpad,
    PivotTriggerKind,
)


def test_lossless_context_pivot_basic_flow() -> None:
    """Verifies lossless context pivot wipes the window, injects scratchpad, and preserves original."""
    engine = LosslessContextPivotEngine()
    session_id = "session_pivot_alpha"

    current_messages: list[dict[str, object]] = [
        {"role": "system", "content": "Initial system instructions."},
        {"role": "user", "content": "Please implement Phase 1 database models."},
        {"role": "assistant", "content": "Creating models and running migration scripts."},
        {
            "role": "tool",
            "content": (
                "Migration executed successfully with 15 tables created.\n"
                + "Schema definition dump:\n"
                + "CREATE TABLE audit_logs (id TEXT PRIMARY KEY, payload TEXT, created_at REAL);\n" * 50
            ),
        },
        {"role": "assistant", "content": "Phase 1 database models are completely wired."},
    ]

    scratchpad = HandoffScratchpad(
        phase_title="Phase 1 Complete -> Transitioning to Phase 2 API Endpoints",
        completed_goals=[
            "Established SQLite schema with FTS5 virtual tables",
            "Added migration test suite with 100% coverage",
        ],
        architectural_decisions=[
            "Decoupled scratchpad reset from lossy message compaction",
            "Used zero-compaction message archival for auditable recovery",
        ],
        active_file_paths=[
            "src/myrm_agent_harness/database/schema.py",
            "tests/database/test_schema.py",
        ],
        next_step_objectives=[
            "Implement FastAPI CRUD routes",
            "Write integration tests for API endpoints",
        ],
        raw_notes_markdown="Notice: keep token footprint minimal across clean turns.",
    )

    result: ContextPivotResult = engine.pivot_to_clean_context(
        session_id=session_id,
        current_messages=current_messages,
        scratchpad=scratchpad,
        base_system_prompt="You are a senior full-stack AI architect.",
    )

    # 1. Result contract assertions
    assert result.session_id == session_id
    assert result.snapshot_id.startswith("snap_")
    assert result.trigger_kind == PivotTriggerKind.AGENT_AUTONOMOUS
    assert result.prior_message_count == 5
    assert result.reclaimed_tokens_estimate > 0
    assert result.pivot_duration_ms >= 0.0

    # 2. Clean messages assertions
    assert len(result.clean_messages) == 2
    sys_msg = result.clean_messages[0]
    user_msg = result.clean_messages[1]

    assert sys_msg["role"] == "system"
    sys_content = str(sys_msg["content"])
    assert "You are a senior full-stack AI architect." in sys_content
    assert "=== ACTIVE PHASE HANDOFF SCRATCHPAD ===" in sys_content
    assert '<handoff-scratchpad phase="Phase 1 Complete -> Transitioning to Phase 2 API Endpoints">' in sys_content
    assert "<completed-goals>" in sys_content
    assert "<architectural-decisions>" in sys_content
    assert "<active-files>" in sys_content
    assert "<next-step-objectives>" in sys_content
    assert "<additional-notes>" in sys_content

    assert user_msg["role"] == "user"
    user_content = str(user_msg["content"])
    assert "Please proceed directly with the next objectives defined in the handoff scratchpad" in user_content

    # 3. Serialization assertion
    res_dict = result.to_dict()
    assert res_dict["session_id"] == session_id
    assert res_dict["clean_message_count"] == 2
    assert res_dict["trigger_kind"] == "agent_autonomous"


def test_handoff_scratchpad_formatting_and_serialization() -> None:
    """Verifies XML output structure and dictionary serialization for HandoffScratchpad."""
    scratchpad = HandoffScratchpad(
        phase_title="Refactoring Milestone",
        completed_goals=["Refactored token budget engine"],
        architectural_decisions=[],
        active_file_paths=["engine.py"],
        next_step_objectives=["Run benchmarks"],
        raw_notes_markdown="",
    )

    xml = scratchpad.format_xml()
    assert '<handoff-scratchpad phase="Refactoring Milestone">' in xml
    assert "<completed-goals>\n- Refactored token budget engine\n</completed-goals>" in xml
    assert "<active-files>\n- engine.py\n</active-files>" in xml
    assert "<next-step-objectives>\n- Run benchmarks\n</next-step-objectives>" in xml
    # Empty sections should be cleanly omitted
    assert "<architectural-decisions>" not in xml
    assert "<additional-notes>" not in xml
    assert xml.endswith("</handoff-scratchpad>")

    serialized = scratchpad.to_dict()
    assert serialized["phase_title"] == "Refactoring Milestone"
    assert serialized["completed_goals"] == ["Refactored token budget engine"]
    assert serialized["active_file_paths"] == ["engine.py"]
    assert serialized["architectural_decisions"] == []
    assert serialized["raw_notes_markdown"] == ""


def test_archived_snapshots_and_message_restoration() -> None:
    """Verifies that multiple generation snapshots can be archived and retrieved losslessly."""
    engine = LosslessContextPivotEngine()
    session_id = "session_archive_beta"

    gen1_msgs: list[dict[str, object]] = [
        {"role": "user", "content": "Generation 1 task step."},
        {"role": "assistant", "content": "Generation 1 execution outcome."},
    ]
    pad1 = HandoffScratchpad(phase_title="Gen 1 Checkpoint")

    res1 = engine.pivot_to_clean_context(
        session_id=session_id,
        current_messages=gen1_msgs,
        scratchpad=pad1,
    )

    gen2_msgs: list[dict[str, object]] = [
        {"role": "user", "content": "Generation 2 follow up."},
        {"role": "assistant", "content": "Generation 2 conclusion."},
        {"role": "user", "content": "Generation 2 validation."},
    ]
    pad2 = HandoffScratchpad(phase_title="Gen 2 Checkpoint")

    res2 = engine.pivot_to_clean_context(
        session_id=session_id,
        current_messages=gen2_msgs,
        scratchpad=pad2,
    )

    # Inspect snapshot metadata
    snapshots: list[ArchivedContextSnapshot] = engine.get_archived_snapshots(session_id)
    assert len(snapshots) == 2
    assert snapshots[0].snapshot_id == res1.snapshot_id
    assert snapshots[0].phase_title == "Gen 1 Checkpoint"
    assert snapshots[0].message_count == 2
    assert snapshots[1].snapshot_id == res2.snapshot_id
    assert snapshots[1].phase_title == "Gen 2 Checkpoint"
    assert snapshots[1].message_count == 3

    # Restore archived messages
    restored_gen1 = engine.restore_archived_messages(session_id, res1.snapshot_id)
    assert restored_gen1 is not None
    assert restored_gen1 == gen1_msgs

    restored_gen2 = engine.restore_archived_messages(session_id, res2.snapshot_id)
    assert restored_gen2 is not None
    assert restored_gen2 == gen2_msgs

    # Nonexistent snapshot returns None
    assert engine.restore_archived_messages(session_id, "snap_invalid_999") is None


def test_pivot_config_and_session_clearing() -> None:
    """Verifies custom trigger kinds, custom continuation templates, and session clearing."""
    custom_cfg = ContextPivotConfig(
        trigger_kind=PivotTriggerKind.BUDGET_THRESHOLD,
        inject_continuation_user_prompt=False,
    )
    engine = LosslessContextPivotEngine(default_config=custom_cfg)
    session_id = "session_config_gamma"

    messages: list[dict[str, object]] = [
        {"role": "user", "content": "High token pressure reached."}
    ]
    pad = HandoffScratchpad(phase_title="Budget Overflow Pivot")

    result = engine.pivot_to_clean_context(
        session_id=session_id,
        current_messages=messages,
        scratchpad=pad,
    )

    assert result.trigger_kind == PivotTriggerKind.BUDGET_THRESHOLD
    # Continuation user prompt was disabled, so only the system prompt is present
    assert len(result.clean_messages) == 1
    assert result.clean_messages[0]["role"] == "system"

    # Active scratchpad retrieval
    latest_pad = engine.get_latest_scratchpad(session_id)
    assert latest_pad is not None
    assert latest_pad.phase_title == "Budget Overflow Pivot"

    # Session clearing
    engine.clear_session(session_id)
    assert engine.get_archived_snapshots(session_id) == []
    assert engine.get_latest_scratchpad(session_id) is None
