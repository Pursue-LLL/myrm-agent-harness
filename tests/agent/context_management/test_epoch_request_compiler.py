# ============================================================================
# Unit Tests for Epoch Request Compiler & Generational Tracking (Item 157)
# ============================================================================

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.epoch import (
    DeterministicToolCompiler,
    EpochHeaderRecord,
    EpochHeaderTracker,
    EpochPhaseKind,
    FirstDiffAreaKind,
    PrefixDigestTelemetricEngine,
    ProjectedContextDelta,
    ProjectionChangeKind,
    RuntimeContextProjection,
)


def test_deterministic_tool_compiler_order_and_key_invariance() -> None:
    """Validate tools compiled in arbitrary order produce identical ordered output and digest."""
    # List A
    tools_a = [
        ("zebra_tool", "Tool Z", {"b_key": 2, "a_key": 1}),
        ("alpha_tool", "Tool A", {"nested": {"y": 20, "x": 10}}),
        ("beta_tool", "Tool B", {"foo": "bar"}),
    ]
    # List B: reversed order and shuffled JSON key definitions
    tools_b = [
        ("beta_tool", "Tool B", {"foo": "bar"}),
        ("alpha_tool", "Tool A", {"nested": {"x": 10, "y": 20}}),
        ("zebra_tool", "Tool Z", {"a_key": 1, "b_key": 2}),
    ]

    ordered_a, digest_a = DeterministicToolCompiler.compile_tools(tools_a)
    ordered_b, digest_b = DeterministicToolCompiler.compile_tools(tools_b)

    assert len(ordered_a) == 3
    assert [t.name for t in ordered_a] == ["alpha_tool", "beta_tool", "zebra_tool"]
    assert [t.name for t in ordered_b] == ["alpha_tool", "beta_tool", "zebra_tool"]

    # Byte-level identical digest despite dictionary key insertion order
    assert digest_a == digest_b
    assert ordered_a[0].schema_digest == ordered_b[0].schema_digest
    assert ordered_a[1].schema_digest == ordered_b[1].schema_digest
    assert ordered_a[2].schema_digest == ordered_b[2].schema_digest


def test_epoch_header_state_machine_lifecycle() -> None:
    """Validate generational state transitions: INITIAL -> SERIES -> CHANGE -> RESUME."""
    tracker = EpochHeaderTracker(session_id="session-101")
    sys_prompt = "You are an autonomous engineering agent."
    tools_digest = "digest-abc-123"

    # Turn 1: Initial
    ep1 = tracker.record_request(
        provider="deepseek",
        model="deepseek-chat",
        system_prompt=sys_prompt,
        tools_schema_digest=tools_digest,
        temperature=0.0,
    )
    assert ep1.generation == 1
    assert ep1.phase == EpochPhaseKind.INITIAL
    assert ep1.starts_series is True

    # Turn 2: Series (identical prefix configuration)
    ep2 = tracker.record_request(
        provider="deepseek",
        model="deepseek-chat",
        system_prompt=sys_prompt,
        tools_schema_digest=tools_digest,
        temperature=0.0,
    )
    assert ep2.generation == 2
    assert ep2.phase == EpochPhaseKind.SERIES
    assert ep2.starts_series is False
    assert ep2.prefix_digest == ep1.prefix_digest

    # Turn 3: Change (system prompt altered)
    ep3 = tracker.record_request(
        provider="deepseek",
        model="deepseek-chat",
        system_prompt=sys_prompt + " Extra instructions.",
        tools_schema_digest=tools_digest,
        temperature=0.0,
    )
    assert ep3.generation == 3
    assert ep3.phase == EpochPhaseKind.CHANGE
    assert ep3.starts_series is True
    assert ep3.prefix_digest != ep1.prefix_digest

    # Turn 4: Resume simulated
    resumed_tracker = EpochHeaderTracker(session_id="session-101")
    resumed_tracker.mark_resumed()
    ep_resume = resumed_tracker.record_request(
        provider="deepseek",
        model="deepseek-chat",
        system_prompt=sys_prompt,
        tools_schema_digest=tools_digest,
        temperature=0.0,
    )
    assert ep_resume.generation == 1
    assert ep_resume.phase == EpochPhaseKind.RESUME
    assert ep_resume.starts_series is True


def test_runtime_context_projection_delta_contract() -> None:
    """Validate dynamic context projection only appends deltas on mutation or clear."""
    proj = RuntimeContextProjection()
    namespace = "sandbox_guard"

    # 1. First injection -> DELTA_APPEND
    delta1 = proj.project(namespace, "deny_paths: [/etc, /root]")
    assert delta1.kind == ProjectionChangeKind.DELTA_APPEND
    assert delta1.delta_content is not None
    assert "[RuntimeContext: sandbox_guard]" in delta1.delta_content
    assert proj.get_snapshot_hash(namespace) is not None

    # 2. Identical projection -> NOOP (0 tokens)
    delta2 = proj.project(namespace, "deny_paths: [/etc, /root]")
    assert delta2.kind == ProjectionChangeKind.NOOP
    assert delta2.delta_content is None

    # 3. Mutated policy -> DELTA_APPEND
    delta3 = proj.project(namespace, "deny_paths: [/etc, /root, /var]")
    assert delta3.kind == ProjectionChangeKind.DELTA_APPEND
    assert delta3.delta_content is not None
    assert "/var" in delta3.delta_content

    # 4. Clear/invalidate policy -> INVALIDATION_CLEAR
    delta4 = proj.project(namespace, None)
    assert delta4.kind == ProjectionChangeKind.INVALIDATION_CLEAR
    assert delta4.delta_content == "[RuntimeContext: sandbox_guard CLEARED]"
    assert proj.get_snapshot_hash(namespace) is None

    # 5. Subsequent clear -> NOOP
    delta5 = proj.project(namespace, "")
    assert delta5.kind == ProjectionChangeKind.NOOP
    assert delta5.delta_content is None


def test_prefix_digest_telemetry_attribution() -> None:
    """Validate firstDiffArea categorization distinguishing runtime defect vs eviction."""
    tracker = EpochHeaderTracker(session_id="session-202")
    ep1 = tracker.record_request("openai", "gpt-4o", "Base prompt", "tool-digest-1", 0.0)

    # 1. Turn 1 initial telemetry
    diag1 = PrefixDigestTelemetricEngine.diagnose_cache_turn(
        current_epoch=ep1,
        previous_epoch=None,
        cache_read_tokens=0,
        cache_miss_tokens=2500,
    )
    assert diag1.first_diff_area == FirstDiffAreaKind.NONE
    assert diag1.is_runtime_defect is False

    # 2. Full cache hit on turn 2
    ep2 = tracker.record_request("openai", "gpt-4o", "Base prompt", "tool-digest-1", 0.0)
    diag2 = PrefixDigestTelemetricEngine.diagnose_cache_turn(
        current_epoch=ep2,
        previous_epoch=ep1,
        cache_read_tokens=2500,
        cache_miss_tokens=0,
    )
    assert diag2.first_diff_area == FirstDiffAreaKind.NONE
    assert diag2.is_runtime_defect is False

    # 3. Break caused by System Prompt mutation
    ep_sys_mutated = tracker.record_request("openai", "gpt-4o", "Modified prompt", "tool-digest-1", 0.0)
    diag3 = PrefixDigestTelemetricEngine.diagnose_cache_turn(
        current_epoch=ep_sys_mutated,
        previous_epoch=ep2,
        cache_read_tokens=0,
        cache_miss_tokens=2600,
    )
    assert diag3.first_diff_area == FirstDiffAreaKind.SYSTEM_PROMPT
    assert diag3.is_runtime_defect is True

    # 4. Break caused by Tool Schema mutation
    ep_tool_mutated = tracker.record_request("openai", "gpt-4o", "Base prompt", "tool-digest-2", 0.0)
    diag4 = PrefixDigestTelemetricEngine.diagnose_cache_turn(
        current_epoch=ep_tool_mutated,
        previous_epoch=ep2,
        cache_read_tokens=0,
        cache_miss_tokens=2600,
    )
    assert diag4.first_diff_area == FirstDiffAreaKind.TOOL_SCHEMA
    assert diag4.is_runtime_defect is True

    # 5. Break caused by Model parameter mutation
    ep_param_mutated = tracker.record_request("openai", "gpt-4o", "Base prompt", "tool-digest-1", 0.7)
    diag5 = PrefixDigestTelemetricEngine.diagnose_cache_turn(
        current_epoch=ep_param_mutated,
        previous_epoch=ep2,
        cache_read_tokens=0,
        cache_miss_tokens=2600,
    )
    assert diag5.first_diff_area == FirstDiffAreaKind.PARAM_MISMATCH
    assert diag5.is_runtime_defect is True

    # 6. Break caused by message history retroactive tampering
    diag6 = PrefixDigestTelemetricEngine.diagnose_cache_turn(
        current_epoch=ep2,
        previous_epoch=ep1,
        cache_read_tokens=0,
        cache_miss_tokens=2600,
        messages_prefix_intact=False,
    )
    assert diag6.first_diff_area == FirstDiffAreaKind.MESSAGE_HISTORY
    assert diag6.is_runtime_defect is True

    # 7. Prefix identical & messages intact, but missed -> Provider eviction
    diag7 = PrefixDigestTelemetricEngine.diagnose_cache_turn(
        current_epoch=ep2,
        previous_epoch=ep1,
        cache_read_tokens=0,
        cache_miss_tokens=2600,
        messages_prefix_intact=True,
    )
    assert diag7.first_diff_area == FirstDiffAreaKind.PROVIDER_EVICTION
    assert diag7.is_runtime_defect is False
