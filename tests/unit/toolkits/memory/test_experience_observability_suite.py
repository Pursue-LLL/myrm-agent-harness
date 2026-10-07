# [POS]: tests/unit/toolkits/memory/test_experience_observability_suite.py
# [INPUT]: myrm_agent_harness.toolkits.memory.experience_observability
# [OUTPUT]: Unit test suite for zero-refactor host plugin and experience observability

"""Unit tests for zero-refactor host lifecycle plugin and experience observability suite.

P1 suite for Item 108 in topic_01 memory roadmap.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.experience_observability import (
    ExperienceEffectStatus,
    ExperienceObservabilityTracker,
    HostAccessChannel,
    HostPluginConfig,
    LifecycleEventKind,
    ZeroRefactorHostPlugin,
)


def test_default_seeded_metrics_and_traces() -> None:
    """Verify pre-seeded production observability metrics and source session traces."""
    tracker = ExperienceObservabilityTracker()
    metrics = tracker.list_metrics()
    assert len(metrics) >= 5

    metric_ids = {m.entry_id for m in metrics}
    assert "proc_git_push_safe" in metric_ids
    assert "RET-EXC-01" in metric_ids
    assert "BA-REV-01" in metric_ids

    # Verify Git safe push metric
    git_m = tracker.get_metric("proc_git_push_safe")
    assert git_m is not None
    assert git_m.source_session_id == "sess_release_incident_09"
    assert git_m.recall_count >= 100
    assert git_m.effect_status == ExperienceEffectStatus.EFFECTIVE
    assert git_m.success_rate > 0.9

    # Verify session traceability
    trace = tracker.get_trace_evidence("sess_release_incident_09")
    assert trace is not None
    assert "误删" in trace.title or "保护" in trace.title
    assert len(trace.key_evidence_snippets) >= 2


def test_tracker_recall_and_injection_recording() -> None:
    """Verify recording recall and injection increments counters and timestamps."""
    tracker = ExperienceObservabilityTracker()
    initial = tracker.get_metric("proc_git_push_safe")
    assert initial is not None
    old_recalls = initial.recall_count
    old_injections = initial.injection_count

    # Record recall via MCP channel
    updated = tracker.record_recall("proc_git_push_safe", channel=HostAccessChannel.MCP)
    assert updated.recall_count == old_recalls + 1
    assert updated.access_channel == HostAccessChannel.MCP

    # Record injection
    updated_inj = tracker.record_injection("proc_git_push_safe")
    assert updated_inj.injection_count == old_injections + 1

    # Record dynamic entry
    new_entry = tracker.record_recall("new_unseen_proc", channel=HostAccessChannel.SKILL)
    assert new_entry.entry_id == "new_unseen_proc"
    assert new_entry.recall_count == 1


def test_tracker_effect_calculation() -> None:
    """Verify success rate computation and categorical status transitions."""
    tracker = ExperienceObservabilityTracker()

    # Success records keep or improve effective status
    m1 = tracker.record_effect("dynamic_exp_01", is_success=True)
    assert m1.success_count == 1
    assert m1.dispute_count == 0
    assert m1.success_rate == 1.0
    assert m1.effect_status == ExperienceEffectStatus.EFFECTIVE

    # Success and dispute mix -> neutral
    tracker.record_effect("dynamic_exp_01", is_success=False, is_dispute=True)
    m2 = tracker.get_metric("dynamic_exp_01")
    assert m2 is not None
    assert m2.success_count == 1
    assert m2.dispute_count == 1
    assert m2.success_rate == 0.5
    assert m2.effect_status == ExperienceEffectStatus.NEUTRAL

    # Heavy dispute -> adverse status
    tracker.record_effect("dynamic_exp_01", is_success=False, is_dispute=True)
    tracker.record_effect("dynamic_exp_01", is_success=False, is_dispute=True)
    m3 = tracker.get_metric("dynamic_exp_01")
    assert m3 is not None
    assert m3.success_rate < 0.5
    assert m3.effect_status == ExperienceEffectStatus.ADVERSE


def test_zero_refactor_plugin_lifecycle_hooks() -> None:
    """Verify plugin intercepts host events and triggers auto-warmup and commit."""
    tracker = ExperienceObservabilityTracker()
    plugin = ZeroRefactorHostPlugin(
        tracker=tracker,
        config=HostPluginConfig(
            enabled=True,
            auto_warmup=True,
            auto_capture=True,
            auto_commit=True,
            monitored_host="claude_code",
        ),
    )

    # 1. on_session_start
    res_start = plugin.on_session_start("session_test_001")
    assert res_start["action"] == "session_started"
    assert res_start["warmed_up_count"] == 2

    # 2. on_user_message
    res_msg = plugin.on_user_message("session_test_001", "Please inspect production git branches.")
    assert res_msg["action"] == "message_captured"

    # 3. on_tool_call
    res_tool = plugin.on_tool_call("session_test_001", "write_file", status="ok")
    assert res_tool["action"] == "tool_call_captured"

    # 4. on_task_completed
    res_comp = plugin.on_task_completed("session_test_001", outcome_status="success")
    assert res_comp["action"] == "task_completed"
    assert res_comp["auto_committed"] is True

    # Intercepted events list
    events = plugin.intercepted_events
    assert len(events) == 4
    kinds = [e.event_kind for e in events]
    assert kinds == [
        LifecycleEventKind.SESSION_START,
        LifecycleEventKind.USER_MESSAGE,
        LifecycleEventKind.TOOL_CALL,
        LifecycleEventKind.TASK_COMPLETED,
    ]


def test_plugin_disabled_and_config_mutation() -> None:
    """Verify plugin operations when disabled and updating configuration."""
    tracker = ExperienceObservabilityTracker()
    plugin = ZeroRefactorHostPlugin(tracker=tracker, config=HostPluginConfig(enabled=False))

    # All hooks safely skip when disabled
    r1 = plugin.on_session_start("sess_inactive")
    assert r1["action"] == "skipped"

    r2 = plugin.on_user_message("sess_inactive", "Hi")
    assert r2["action"] == "skipped"

    r3 = plugin.on_task_completed("sess_inactive")
    assert r3["action"] == "skipped"

    # Re-enable and switch channel to MCP
    plugin.update_config(enabled=True, active_channel=HostAccessChannel.MCP, monitored_host="cursor")
    assert plugin.config.enabled is True
    assert plugin.config.active_channel == HostAccessChannel.MCP
    assert plugin.config.monitored_host == "cursor"
