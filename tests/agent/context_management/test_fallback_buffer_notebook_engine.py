"""Unit tests for Auto-Compact Fallback Buffer and Team Notebook Suite (Item 223).

[INPUT]
- FallbackBufferNotebookEngine, FallbackBufferConfig, BufferWatermarkState, TeamNotebookEntry.
- Simulated token headrooms, subagent milestone notes, and compaction alert triggers.

[OUTPUT]
- Deterministic verification of token watermark guards, fallback compaction triggering,
- shared multi-agent scratchpad relay, and transparent compaction consequence banners.

[POS]
- Verifies prevention of fatal context OOMs via reserve buffers and smooth subagent handoff.
"""

from __future__ import annotations

import time
import pytest

from myrm_agent_harness.agent.context_management.fallback_buffer_notebook import (
    BufferWatermarkSnapshot,
    BufferWatermarkState,
    CompactionConsequenceAlert,
    FallbackBufferConfig,
    FallbackBufferNotebookEngine,
    TeamNotebookEntry,
    TeamNotebookSnapshot,
)


def test_watermark_assessment_and_fallback_trigger() -> None:
    """Verifies token watermark levels, safety buffer headroom, and fallback trigger transitions."""
    config = FallbackBufferConfig(
        context_window_limit=100000,
        fallback_buffer_tokens=8000,  # Safe ceiling = 92000
        warning_threshold_ratio=0.85,  # Warning threshold = 78200
    )
    engine = FallbackBufferNotebookEngine(config=config)

    # 1. Normal safe operation
    s_safe = engine.assess_watermark(current_tokens=50000)
    assert s_safe.watermark_state == BufferWatermarkState.SAFE
    assert s_safe.safe_ceiling_tokens == 92000
    assert engine.is_fallback_compaction_required(50000) is False

    # 2. Approaching warning
    s_warn = engine.assess_watermark(current_tokens=80000)
    assert s_warn.watermark_state == BufferWatermarkState.WARNING_APPROACHING
    assert engine.is_fallback_compaction_required(80000) is False

    # 3. Breaching safe ceiling -> FALLBACK_TRIGGERED
    s_trigger = engine.assess_watermark(current_tokens=93000)
    assert s_trigger.watermark_state == BufferWatermarkState.FALLBACK_TRIGGERED
    assert engine.is_fallback_compaction_required(93000) is True
    assert s_trigger.remaining_buffer_tokens == 7000

    # 4. Critical physical boundary
    s_crit = engine.assess_watermark(current_tokens=100050)
    assert s_crit.watermark_state == BufferWatermarkState.CRITICAL_EXHAUSTED


def test_fallback_compaction_instruction_generation() -> None:
    """Verifies generation of emergency fallback prompt utilizing reserved buffer allowance."""
    engine = FallbackBufferNotebookEngine()
    snapshot = engine.assess_watermark(current_tokens=121000)

    prompt = engine.generate_fallback_compact_instruction(snapshot)
    assert "<emergency_fallback_compaction>" in prompt
    assert "121000 tokens breached safe ceiling" in prompt
    assert "8000 tokens allocated" in prompt
    assert "[Preservation Mandate]:" in prompt


def test_multiagent_team_notebook_relay() -> None:
    """Verifies shared workspace scratchpad compilation across sequential subagents."""
    engine = FallbackBufferNotebookEngine()

    now = time.time()

    # Subagent A: Process 0-30m segment
    entry_a = TeamNotebookEntry(
        note_id="note_001",
        session_id="sess_meeting_relay",
        agent_role="AudioSubagent_A",
        section_title="Minutes 0-30 Highlights",
        content="Decided to approve Q3 budget allocation ($1.2M). Deferred hiring plan.",
        subtask_index=0,
        timestamp=now - 100,
    )
    snap_a = engine.append_notebook_entry(entry_a)
    assert snap_a.total_notes == 1
    assert snap_a.last_updated_by == "AudioSubagent_A"
    assert "Decided to approve Q3 budget" in snap_a.compiled_markdown

    # Subagent B: Read and pick up 30-60m segment
    read_b = engine.read_notebook_snapshot("sess_meeting_relay")
    assert read_b.total_notes == 1

    entry_b = TeamNotebookEntry(
        note_id="note_002",
        session_id="sess_meeting_relay",
        agent_role="AudioSubagent_B",
        section_title="Minutes 30-60 Highlights",
        content="Reviewed technical architecture for Project Pegasus. Target go-live Nov 15.",
        subtask_index=1,
        timestamp=now,
    )
    snap_b = engine.append_notebook_entry(entry_b)
    assert snap_b.total_notes == 2
    assert snap_b.last_updated_by == "AudioSubagent_B"
    assert "Project Pegasus" in snap_b.compiled_markdown
    assert "Subtask #0" in snap_b.compiled_markdown
    assert "Subtask #1" in snap_b.compiled_markdown


def test_compaction_consequence_alert_generation_and_clear() -> None:
    """Verifies transparent user alert generation and clean teardown."""
    engine = FallbackBufferNotebookEngine()

    snapshot = engine.assess_watermark(current_tokens=122000)
    alert = engine.generate_compaction_alert(
        session_id="sess_alert_1",
        snapshot=snapshot,
        compacted_turn_range="Turns 1-28",
        preserved_decision_summary="Database schema v3 confirmed; API contract locked",
        archived_ledger_ref="sqlite://session_action_ledger?session=sess_alert_1",
    )

    assert alert.session_id == "sess_alert_1"
    assert "122000/128000" in alert.user_banner_text
    assert "Turns 1-28" in alert.user_banner_text
    assert "Database schema v3 confirmed" in alert.user_banner_text

    alerts = engine.get_session_alerts("sess_alert_1")
    assert len(alerts) == 1
    assert alerts[0].alert_id == alert.alert_id

    # Clear session
    engine.clear_session("sess_alert_1")
    assert len(engine.get_session_alerts("sess_alert_1")) == 0
    empty_snap = engine.read_notebook_snapshot("sess_alert_1")
    assert empty_snap.total_notes == 0
