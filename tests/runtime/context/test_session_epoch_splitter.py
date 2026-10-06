"""Tests for Auto-Forking Milestone Checkpoint Archiver & Long-Session Epoch Splitter."""

from myrm_agent_harness.runtime.context.session_epoch_splitter import (
    EpochSplitUrgency,
    LongSessionEpochSplitter,
    MilestoneArtifactRef,
    MilestoneCheckpointArchiver,
    SessionSaturationGovernor,
)


def test_saturation_probe_levels():
    # 1. Nominal capacity
    rep_normal = SessionSaturationGovernor.probe_saturation(
        message_count=120,
        estimated_tokens=25_000,
        max_context_window=128_000,
    )
    assert rep_normal.urgency == EpochSplitUrgency.NORMAL
    assert not rep_normal.should_auto_fork
    assert rep_normal.saturation_ratio < 0.3

    # 2. Warning boundary by message count
    rep_warn_msgs = SessionSaturationGovernor.probe_saturation(
        message_count=850,
        estimated_tokens=50_000,
        max_context_window=128_000,
    )
    assert rep_warn_msgs.urgency == EpochSplitUrgency.WARNING
    assert not rep_warn_msgs.should_auto_fork

    # 3. Warning boundary by token ratio
    rep_warn_tokens = SessionSaturationGovernor.probe_saturation(
        message_count=300,
        estimated_tokens=95_000,
        max_context_window=128_000,
    )
    assert rep_warn_tokens.urgency == EpochSplitUrgency.WARNING
    assert not rep_warn_tokens.should_auto_fork

    # 4. Critical auto-fork threshold by message count (1500+)
    rep_crit = SessionSaturationGovernor.probe_saturation(
        message_count=1520,
        estimated_tokens=70_000,
        max_context_window=128_000,
    )
    assert rep_crit.urgency == EpochSplitUrgency.CRITICAL
    assert rep_crit.should_auto_fork

    # 5. Immediate hard limit (2000 msgs or 95%+ ratio)
    rep_hard = SessionSaturationGovernor.probe_saturation(
        message_count=2001,
        estimated_tokens=110_000,
        max_context_window=128_000,
    )
    assert rep_hard.urgency == EpochSplitUrgency.SPLIT_IMMEDIATELY
    assert rep_hard.should_auto_fork


def test_milestone_checkpoint_archiver_and_preamble_render():
    artifacts = (
        MilestoneArtifactRef(
            path="src/kernel/engine.py",
            version="v2.1",
            summary="High-performance async kernel execution loop",
        ),
        MilestoneArtifactRef(
            path="config/settings.yaml",
            version="v1.0",
            summary="Production cluster deployment configuration",
        ),
    )
    checkpoint = MilestoneCheckpointArchiver.generate_checkpoint(
        session_id="sess-alpha-001",
        epoch_index=1,
        parent_session_id=None,
        completed_goals=("Setup Redis backend", "Refactor session state parser"),
        pending_tasks=("Implement rate-limiting middleware", "Conduct integration load tests"),
        active_artifacts=artifacts,
        key_decisions=("Adopt SQLite + WAL mode for local persistent cache",),
        created_at_utc="2026-10-06T14:00:00Z",
    )

    assert checkpoint.session_id == "sess-alpha-001"
    assert checkpoint.epoch_index == 1
    assert len(checkpoint.active_artifacts) == 2

    xml = MilestoneCheckpointArchiver.render_milestone_preamble(checkpoint)
    assert '<milestone_epoch_preamble version="1.0">' in xml
    assert '<parent_origin session_id="sess-alpha-001" epoch_index="1"' in xml
    assert "<goal>Setup Redis backend</goal>" in xml
    assert "<decision>Adopt SQLite + WAL mode for local persistent cache</decision>" in xml
    assert '<artifact path="src/kernel/engine.py" version="v2.1">High-performance async kernel execution loop</artifact>' in xml
    assert "<task>Implement rate-limiting middleware</task>" in xml
    assert "</milestone_epoch_preamble>" in xml


def test_long_session_epoch_splitter_fork():
    descriptor = LongSessionEpochSplitter.fork_next_epoch(
        source_session_id="sess-proj-large",
        current_epoch_index=1,
        completed_goals=("Finished database migrations", "Closed API schema contracts"),
        pending_tasks=("Build Vue/React dashboard",),
        active_artifacts=(
            MilestoneArtifactRef(path="schema.sql", version="1.2", summary="DB Schema"),
        ),
        key_decisions=("Use UUIDv7 for all primary keys",),
        created_at_utc="2026-10-06T15:00:00Z",
    )

    assert descriptor.next_session_id == "sess-proj-large_epoch_2"
    assert descriptor.parent_session_id == "sess-proj-large"
    assert descriptor.epoch_index == 2
    assert descriptor.checkpoint.epoch_index == 1
    assert "<milestone_epoch_preamble" in descriptor.hydrated_preamble
    assert "UUIDv7" in descriptor.hydrated_preamble


def test_custom_next_session_id_generator():
    descriptor = LongSessionEpochSplitter.fork_next_epoch(
        source_session_id="session-xyz",
        current_epoch_index=3,
        completed_goals=("Goal A",),
        pending_tasks=(),
        active_artifacts=(),
        key_decisions=(),
        created_at_utc="2026-10-06T15:30:00Z",
        next_session_id_generator=lambda src, ep: f"custom-{src}-stage-{ep}",
    )

    assert descriptor.next_session_id == "custom-session-xyz-stage-4"
    assert descriptor.epoch_index == 4
