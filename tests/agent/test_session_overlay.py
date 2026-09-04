"""Tests for the continual fault-site session overlay subsystem."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.session_overlay.manager import (
    MAX_ACTIVE_OVERLAYS,
    SessionOverlayManager,
)
from myrm_agent_harness.agent.session_overlay.schema import (
    OverlayScope,
    OverlayStatus,
    OverlayTargetType,
    SessionOverlay,
)
from myrm_agent_harness.agent.session_overlay.synthesizer import (
    synthesize_fault_site_overlay,
    synthesize_loop_stall_overlay,
)


def test_schema_serialization_and_compatibility() -> None:
    """Verify SessionOverlay properties and dictionary serialization."""
    ovl = SessionOverlay(
        overlay_id="ovl-test-1",
        scope=OverlayScope.SESSION,
        target_type=OverlayTargetType.TEMP_SKILL_VARIANT,
        target_name="run_script",
        patch_payload={
            "strip_params": ["color_palette"],
            "advisory_instruction": "Omit color_palette",
        },
        ttl_turns=3,
        failure_signature="run_script:extra_field",
        created_at_turn=1,
    )
    assert ovl.is_alive() is True
    assert ovl.shell_type == OverlayTargetType.TEMP_SKILL_VARIANT
    assert ovl.remaining_turns == 3
    assert ovl.trigger_reason == "run_script:extra_field"
    assert ovl.patch_data["strip_params"] == ["color_palette"]

    data = ovl.to_dict()
    assert data["overlayId"] == "ovl-test-1"
    assert data["shellType"] == "skill_variant"
    assert data["remainingTurns"] == 3
    assert data["triggerReason"] == "run_script:extra_field"
    assert data["advisoryText"] == "Omit color_palette"


def test_synthesizer_extra_argument_strip() -> None:
    """Verify dual-track L0/L1 synthesis from Pydantic extra-field errors."""
    error_msg = "ValidationError: 1 validation error for ToolArgs\nextra field 'legacy_fmt' not permitted (type=value_error.extra)"
    tool_args: dict[str, object] = {"data": "test.csv", "legacy_fmt": "json"}

    ovl = synthesize_fault_site_overlay(
        tool_name="export_tool",
        error=error_msg,
        tool_args=tool_args,
        current_turn=2,
    )
    assert ovl is not None
    assert ovl.target_type == OverlayTargetType.TEMP_SKILL_VARIANT
    assert ovl.target_name == "export_tool"
    assert ovl.patch_payload["strip_params"] == ["legacy_fmt"]
    assert "extra_arg_legacy_fmt" in ovl.failure_signature
    assert ovl.ttl_turns == 3


def test_synthesizer_timeout_procedural_memory() -> None:
    """Verify synthesis from timeout errors produces procedural negative constraints."""
    ovl = synthesize_fault_site_overlay(
        tool_name="web_search",
        error="TimeoutError: Search request deadline exceeded after 30s",
        tool_args={"q": "long complex query"},
        current_turn=5,
    )
    assert ovl is not None
    assert ovl.target_type == OverlayTargetType.PROCEDURAL_MEMORY
    assert "timeout" in ovl.failure_signature
    assert "timed out" in str(ovl.patch_payload.get("negative_constraint"))


def test_synthesizer_loopguard_stall() -> None:
    """Verify LoopGuard stall warnings trigger procedural negative memory overlays."""
    ovl = synthesize_loop_stall_overlay(
        loop_kind="ping_pong",
        tool_name="web_fetch",
        current_turn=4,
    )
    assert ovl.target_type == OverlayTargetType.PROCEDURAL_MEMORY
    assert ovl.target_name == "web_fetch"
    assert "ping_pong" in ovl.failure_signature
    assert "do not repeat identical invocations" in str(ovl.patch_payload.get("negative_constraint"))


def test_manager_register_and_adaptation() -> None:
    """Verify manager registers overlays and applies argument-stripping adaptation."""
    mgr = SessionOverlayManager(session_id="test_sess_1")
    ovl = SessionOverlay(
        overlay_id="ovl-adapt-1",
        scope=OverlayScope.SESSION,
        target_type=OverlayTargetType.TEMP_SKILL_VARIANT,
        target_name="calculate_tax",
        patch_payload={"strip_params": ["deprecated_rate"]},
        ttl_turns=2,
    )
    mgr.register_overlay(ovl)

    active = mgr.get_active_overlays(target_name="calculate_tax")
    assert len(active) == 1
    assert active[0].overlay_id == "ovl-adapt-1"

    # Pre-execution adaptation
    raw_args: dict[str, object] = {"income": 100000, "deprecated_rate": 0.2, "year": 2026}
    adapted_args, applied = mgr.apply_tool_args_adaptation("calculate_tax", raw_args)
    assert applied is not None
    assert "deprecated_rate" not in adapted_args
    assert adapted_args["income"] == 100000
    assert adapted_args["year"] == 2026


def test_manager_max_active_eviction() -> None:
    """Verify manager caps active overlays at MAX_ACTIVE_OVERLAYS to prevent cascade."""
    mgr = SessionOverlayManager(session_id="test_sess_cap")
    for i in range(MAX_ACTIVE_OVERLAYS + 2):
        ovl = SessionOverlay(
            overlay_id=f"ovl-{i}",
            scope=OverlayScope.SESSION,
            target_type=OverlayTargetType.PROCEDURAL_MEMORY,
            target_name=f"tool_{i}",
            patch_payload={"negative_constraint": f"constraint {i}"},
            ttl_turns=3,
        )
        mgr.register_overlay(ovl)

    active = mgr.get_active_overlays()
    assert len(active) <= MAX_ACTIVE_OVERLAYS


def test_manager_trial_and_rollback_guard() -> None:
    """Verify single-shot Trial & Rollback Guard: failure triggers immediate rollback."""
    mgr = SessionOverlayManager(session_id="test_sess_rollback")
    ovl = SessionOverlay(
        overlay_id="ovl-trial-1",
        scope=OverlayScope.SESSION,
        target_type=OverlayTargetType.TEMP_SKILL_VARIANT,
        target_name="flaky_tool",
        patch_payload={"strip_params": ["bad_arg"]},
        ttl_turns=3,
    )
    mgr.register_overlay(ovl)

    # Tool executes and fails again -> Trial failed, physical rollback
    rolled_back = mgr.record_tool_outcome("flaky_tool", is_error=True, error_signature="flaky_tool:Crash")
    assert "ovl-trial-1" in rolled_back

    # Active overlays should now be empty
    active = mgr.get_active_overlays(target_name="flaky_tool")
    assert len(active) == 0


def test_manager_ttl_turn_decrement_and_growth_export() -> None:
    """Verify turn consumption decrements TTL and verified overlays export to Growth."""
    mgr = SessionOverlayManager(session_id="test_sess_ttl")
    ovl = SessionOverlay(
        overlay_id="ovl-success-1",
        scope=OverlayScope.SESSION,
        target_type=OverlayTargetType.TEMP_SKILL_VARIANT,
        target_name="clean_tool",
        patch_payload={"strip_params": ["old_field"]},
        ttl_turns=2,
    )
    mgr.register_overlay(ovl)

    # Tool executes successfully under overlay
    mgr.record_tool_outcome("clean_tool", is_error=False)

    # Turn 1: already decremented by successful tool outcome (TTL 2 -> 1)
    active = mgr.get_active_overlays()
    assert len(active) == 1
    assert active[0].ttl_turns == 1

    # Turn 2: consume_turn() decrements TTL 1 -> 0 (Expired gracefully)
    expired = mgr.consume_turn()
    assert "ovl-success-1" in expired
    assert len(mgr.get_active_overlays()) == 0

    # Growth export should contain the successfully verified overlay
    manifests = mgr.export_growth_manifests()
    assert len(manifests) == 1
    assert manifests[0]["overlay_id"] == "ovl-success-1"
    assert manifests[0]["target_name"] == "clean_tool"


def test_session_overlay_idempotent_refresh_and_manual_rollback() -> None:
    """Verify deduplication/refresh on same target and manual rollback API."""
    mgr = SessionOverlayManager("test-idempotent")
    ovl1 = SessionOverlay(
        overlay_id="ovl-dup-1",
        scope=OverlayScope.SESSION,
        target_type=OverlayTargetType.TEMP_SKILL_VARIANT,
        target_name="fetch_api",
        patch_payload={"strip_params": ["timeout"]},
        ttl_turns=3,
        status=OverlayStatus.ACTIVE,
    )
    assert mgr.register_overlay(ovl1) is True

    # Register second overlay on same target_name and target_type
    ovl2 = SessionOverlay(
        overlay_id="ovl-dup-2",
        scope=OverlayScope.SESSION,
        target_type=OverlayTargetType.TEMP_SKILL_VARIANT,
        target_name="fetch_api",
        patch_payload={"strip_params": ["timeout", "retries"]},
        ttl_turns=5,
        status=OverlayStatus.ACTIVE,
    )
    assert mgr.register_overlay(ovl2) is True

    # Should have refreshed the existing one instead of adding another
    active = mgr.get_active_overlays()
    assert len(active) == 1
    assert active[0].overlay_id == "ovl-dup-1"
    assert active[0].ttl_turns == 5
    assert active[0].attempt_count == 1
    assert active[0].patch_payload.get("strip_params") == ["timeout", "retries"]

    # Test manual rollback
    assert mgr.rollback_overlay("ovl-dup-1") is True
    assert len(mgr.get_active_overlays()) == 0
    assert mgr.rollback_overlay("non-existent") is False


def test_fatal_system_errors_fuse_protection() -> None:
    """Verify that unrecoverable system errors short-circuit and never synthesize overlays."""
    # 1. MemoryError
    res1 = synthesize_fault_site_overlay("heavy_compute", error=MemoryError("Out of memory"))
    assert res1 is None

    # 2. PermissionError
    res2 = synthesize_fault_site_overlay("file_writer", error=PermissionError("Permission denied: /etc/shadow"))
    assert res2 is None

    # 3. Disk full (ENOSPC string pattern)
    res3 = synthesize_fault_site_overlay("db_dump", error="OSError: [Errno 28] No space left on device: enospc")
    assert res3 is None


def test_manager_rollback_counter_and_step_lifecycle() -> None:
    """Verify rollback tracking and step-based TTL decrement upon successful usage."""
    mgr = SessionOverlayManager("test-rollback-counter")
    ovl = SessionOverlay(
        overlay_id="ovl-step-1",
        scope=OverlayScope.SESSION,
        target_type=OverlayTargetType.TEMP_SKILL_VARIANT,
        target_name="api_tool",
        patch_payload={"strip_params": ["bad_param"]},
        ttl_turns=1,
    )
    mgr.register_overlay(ovl)

    # 1. Tool succeeds under overlay: decrements TTL from 1 to 0 and auto-expires
    mgr.record_tool_outcome("api_tool", is_error=False)
    assert len(mgr.get_active_overlays()) == 0
    assert mgr.total_rollbacks == 0

    # 2. Tool fails under a new overlay: triggers rollback and increments total_rollbacks
    ovl2 = SessionOverlay(
        overlay_id="ovl-step-2",
        scope=OverlayScope.SESSION,
        target_type=OverlayTargetType.TEMP_SKILL_VARIANT,
        target_name="api_tool_2",
        patch_payload={"strip_params": ["bad_param"]},
        ttl_turns=3,
    )
    mgr.register_overlay(ovl2)
    mgr.record_tool_outcome("api_tool_2", is_error=True, error_signature="Crash")
    assert mgr.total_rollbacks == 1
    assert len(mgr.get_active_overlays()) == 0


def test_synthesizer_unexpected_keyword_argument_and_ast_edge_cases() -> None:
    """Verify various unexpected keyword argument formats and casing are handled cleanly."""
    # 1. TypeError with unexpected keyword argument
    err_msg = "TypeError: fetch() got an unexpected keyword argument 'custom_header_x'"
    ovl = synthesize_fault_site_overlay(
        tool_name="fetch",
        error=err_msg,
        tool_args={"url": "https://example.com", "custom_header_x": "Bearer 123"},
    )
    assert ovl is not None
    assert ovl.patch_payload.get("strip_params") == ["custom_header_x"]

    # 2. Unknown parameter in JSON error
    err_msg_json = "ClientError: unknown parameter: filter_by_tag"
    ovl2 = synthesize_fault_site_overlay(
        tool_name="search",
        error=err_msg_json,
        tool_args={"query": "test", "filter_by_tag": "v1"},
    )
    assert ovl2 is not None
    assert ovl2.patch_payload.get("strip_params") == ["filter_by_tag"]


def test_multi_overlay_cross_target_isolation_and_growth_payload() -> None:
    """Verify cross-target isolation and verify payload compatibility with Server Growth."""
    mgr = SessionOverlayManager("test-multi-target-isolation")

    ovl_a = SessionOverlay(
        overlay_id="ovl-target-a",
        scope=OverlayScope.SESSION,
        target_type=OverlayTargetType.TEMP_SKILL_VARIANT,
        target_name="tool_a",
        patch_payload={"strip_params": ["arg_a"]},
        ttl_turns=2,
    )
    ovl_b = SessionOverlay(
        overlay_id="ovl-target-b",
        scope=OverlayScope.SESSION,
        target_type=OverlayTargetType.TEMP_SKILL_VARIANT,
        target_name="tool_b",
        patch_payload={"strip_params": ["arg_b"]},
        ttl_turns=2,
    )
    mgr.register_overlay(ovl_a)
    mgr.register_overlay(ovl_b)

    # Cross-target adaptation isolation: tool_a only strips arg_a, not arg_b
    args_a = {"data": 123, "arg_a": "bad_a", "arg_b": "keep_b"}
    adapted_a, applied_a = mgr.apply_tool_args_adaptation("tool_a", args_a)
    assert applied_a is not None
    assert "arg_a" not in adapted_a
    assert adapted_a["arg_b"] == "keep_b"

    # Tool_b adaptation only strips arg_b, not arg_a
    args_b = {"data": 456, "arg_a": "keep_a", "arg_b": "bad_b"}
    adapted_b, applied_b = mgr.apply_tool_args_adaptation("tool_b", args_b)
    assert applied_b is not None
    assert "arg_b" not in adapted_b
    assert adapted_b["arg_a"] == "keep_a"

    # Verify tool_a success only consumes tool_a's TTL
    mgr.record_tool_outcome("tool_a", is_error=False)
    active_a = mgr.get_active_overlays(target_name="tool_a")
    active_b = mgr.get_active_overlays(target_name="tool_b")
    assert len(active_a) == 1
    assert active_a[0].ttl_turns == 1  # 2 - 1
    assert len(active_b) == 1
    assert active_b[0].ttl_turns == 2  # untouched!



