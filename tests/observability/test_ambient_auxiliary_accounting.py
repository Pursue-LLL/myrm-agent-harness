"""[INPUT] Ambient auxiliary task context and tracker telemetry.
[OUTPUT] Unit tests verifying prompt cache purity preservation and task dimension attribution.
[POS] myrm-agent-harness/tests/observability/test_ambient_auxiliary_accounting.py
"""

from myrm_agent_harness.observability.ambient_auxiliary_accounting import (
    AmbientAccountingReport,
    AmbientAuxiliaryAccountingTracker,
    AuxiliaryTaskType,
    ambient_auxiliary_task,
    get_current_ambient_task,
)


def test_context_manager_scoping_and_nesting() -> None:
    """Verifies that ambient_auxiliary_task sets and cleanly restores contextvars."""
    # Outside context: should default to MAIN_DIALOGUE
    default_task, custom_name, model_override = get_current_ambient_task()
    assert default_task == AuxiliaryTaskType.MAIN_DIALOGUE
    assert custom_name == ""
    assert model_override == ""

    # Enter background reflection context
    with ambient_auxiliary_task(AuxiliaryTaskType.BACKGROUND_REFLECTION, custom_task_name="reviewer", model="gpt-4o-mini"):
        curr_task, curr_custom, curr_model = get_current_ambient_task()
        assert curr_task == AuxiliaryTaskType.BACKGROUND_REFLECTION
        assert curr_custom == "reviewer"
        assert curr_model == "gpt-4o-mini"

        # Nested context: context compression
        with ambient_auxiliary_task(AuxiliaryTaskType.CONTEXT_COMPRESSION, model="qwen-2.5"):
            nested_task, nested_custom, nested_model = get_current_ambient_task()
            assert nested_task == AuxiliaryTaskType.CONTEXT_COMPRESSION
            assert nested_model == "qwen-2.5"

        # Back to outer reflection context
        back_task, back_custom, back_model = get_current_ambient_task()
        assert back_task == AuxiliaryTaskType.BACKGROUND_REFLECTION
        assert back_custom == "reviewer"
        assert back_model == "gpt-4o-mini"

    # Restored to root
    restored_task, _, _ = get_current_ambient_task()
    assert restored_task == AuxiliaryTaskType.MAIN_DIALOGUE


def test_tracker_sniffs_ambient_context() -> None:
    """Verifies that tracker automatically associates usage with the current active ambient context."""
    tracker = AmbientAuxiliaryAccountingTracker()

    # 1. Root call without context
    snap_main = tracker.record_invocation(
        session_id="sess_101",
        input_tokens=1500,
        output_tokens=300,
        duration_ms=450.0,
        cost_usd=0.015,
    )
    assert snap_main.task_type == AuxiliaryTaskType.MAIN_DIALOGUE
    assert snap_main.effective_task_name == "main_dialogue"

    # 2. Ambient call inside context
    with ambient_auxiliary_task(AuxiliaryTaskType.CUSTOM, custom_task_name="auto_summary"):
        snap_aux = tracker.record_invocation(
            session_id="sess_101",
            input_tokens=800,
            output_tokens=120,
            duration_ms=210.0,
            cost_usd=0.005,
        )
        assert snap_aux.task_type == AuxiliaryTaskType.CUSTOM
        assert snap_aux.effective_task_name == "auto_summary"

    # Verify recent snapshots
    snaps = tracker.get_recent_snapshots(session_id="sess_101")
    assert len(snaps) == 2


def test_tracker_report_aggregation_and_attribution() -> None:
    """Verifies cost aggregation, percentage share, and task grouping."""
    tracker = AmbientAuxiliaryAccountingTracker()

    # Main dialogue call: $0.03
    tracker.record_invocation(
        session_id="sess_200",
        input_tokens=3000,
        output_tokens=600,
        cost_usd=0.030,
        task_type=AuxiliaryTaskType.MAIN_DIALOGUE,
    )

    # Context compression call: $0.01
    tracker.record_invocation(
        session_id="sess_200",
        input_tokens=2000,
        output_tokens=100,
        cost_usd=0.010,
        task_type=AuxiliaryTaskType.CONTEXT_COMPRESSION,
    )

    # Vision prep call: $0.01
    tracker.record_invocation(
        session_id="sess_200",
        input_tokens=1000,
        output_tokens=50,
        cost_usd=0.010,
        task_type=AuxiliaryTaskType.VISION_PREP,
    )

    report: AmbientAccountingReport = tracker.get_accounting_report(session_id="sess_200")
    assert report.total_invocations == 3
    assert abs(report.total_cost_usd - 0.050) < 1e-4
    assert abs(report.core_dialogue_cost_usd - 0.030) < 1e-4
    assert abs(report.auxiliary_cost_usd - 0.020) < 1e-4
    # Aux share = 0.02 / 0.05 = 40.0%
    assert abs(report.auxiliary_cost_share_pct - 40.0) < 0.1
    assert report.prompt_cache_purity_preserved is True

    # 3 distinct tasks
    assert len(report.task_summaries) == 3
    task_names = [t.task_name for t in report.task_summaries]
    assert "main_dialogue" in task_names
    assert "context_compression" in task_names
    assert "vision_prep" in task_names


def test_tracker_session_isolation_and_reset() -> None:
    """Verifies session-level filtering and telemetry reset."""
    tracker = AmbientAuxiliaryAccountingTracker()

    tracker.record_invocation(session_id="sess_a", input_tokens=100, output_tokens=20, cost_usd=0.001)
    tracker.record_invocation(session_id="sess_b", input_tokens=200, output_tokens=40, cost_usd=0.002)

    assert len(tracker.get_recent_snapshots(session_id="sess_a")) == 1
    assert len(tracker.get_recent_snapshots(session_id="sess_b")) == 1

    # Reset sess_a only
    tracker.reset(session_id="sess_a")
    assert len(tracker.get_recent_snapshots(session_id="sess_a")) == 0
    assert len(tracker.get_recent_snapshots(session_id="sess_b")) == 1

    # Reset all
    tracker.reset()
    assert len(tracker.get_recent_snapshots()) == 0
