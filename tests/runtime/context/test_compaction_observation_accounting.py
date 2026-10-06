"""Tests for compaction visual observation and host-owned prompt accounting engine."""

from __future__ import annotations

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolCall,
    ToolMessage,
)

from myrm_agent_harness.runtime.context.compaction_observation_accounting import (
    CompactionHysteresisBufferController,
    CompactionObservationCollector,
    CompactionTriggerMode,
    FrameCategory,
    HostOwnedBreakdown,
    HostOwnedPromptAccountingLedger,
)


def test_host_owned_prompt_accounting_ledger_breakdown() -> None:
    """Verify host-owned ledger correctly isolates system prompts and tools overhead."""
    system_text = "You are an expert AI software architect and coding engineer."
    tools_json = '{"tools": [{"name": "read_file", "params": {"path": "str"}}]}'
    skills_text = "Use PEP8 standards and strict type annotations."
    env_meta = "OS: macOS Darwin 24.0.0, Python 3.13"

    ledger = HostOwnedPromptAccountingLedger.calculate_from_sources(
        model_context_window=128000,
        system_prompt=system_text,
        tool_schemas_json=tools_json,
        skill_guidelines=skills_text,
        environment_meta=env_meta,
        safety_reserve_tokens=4000,
    )

    assert ledger.breakdown.system_prompt_tokens > 0
    assert ledger.breakdown.tool_schemas_tokens > 0
    assert ledger.breakdown.skill_guidelines_tokens > 0
    assert ledger.breakdown.environment_meta_tokens > 0

    total_host = ledger.total_host_owned_tokens
    assert total_host == (
        ledger.breakdown.system_prompt_tokens
        + ledger.breakdown.tool_schemas_tokens
        + ledger.breakdown.skill_guidelines_tokens
        + ledger.breakdown.environment_meta_tokens
    )

    expected_capacity = 128000 - total_host - 4000
    assert ledger.effective_compactable_capacity == expected_capacity


def test_host_owned_ledger_clamps_negative_capacity() -> None:
    """Verify effective capacity does not drop below safe lower bound under extreme overhead."""
    ledger = HostOwnedPromptAccountingLedger(
        model_context_window=10000,
        breakdown=HostOwnedBreakdown(
            system_prompt_tokens=8000,
            tool_schemas_tokens=4000,
        ),
        safety_reserve_tokens=4000,
    )
    # 10000 - 12000 - 4000 = -6000 -> clamped to 1000
    assert ledger.effective_compactable_capacity == 1000


def test_hysteresis_buffer_controller_below_high_watermark() -> None:
    """Verify compaction is not triggered when compactable tokens are below high watermark."""
    controller = CompactionHysteresisBufferController(
        high_watermark_ratio=0.80,
        low_watermark_ratio=0.50,
        min_reduction_tokens=2000,
        cooldown_turns=2,
    )
    ledger = HostOwnedPromptAccountingLedger(
        model_context_window=100000,
        breakdown=HostOwnedBreakdown(system_prompt_tokens=10000),
        safety_reserve_tokens=10000,
    )
    # effective_capacity = 80000 -> high_threshold = 64000, low_target = 40000
    decision = controller.evaluate(
        current_compactable_tokens=60000,
        current_turn=5,
        ledger=ledger,
    )

    assert not decision.should_compact
    assert decision.trigger_mode is None
    assert decision.high_watermark_tokens == 64000
    assert decision.target_low_watermark_tokens == 40000
    assert decision.tokens_to_reduce == 0


def test_hysteresis_buffer_controller_triggers_high_watermark() -> None:
    """Verify normal compaction trigger when exceeding high watermark with sufficient reduction."""
    controller = CompactionHysteresisBufferController(
        high_watermark_ratio=0.80,
        low_watermark_ratio=0.50,
        min_reduction_tokens=2000,
        cooldown_turns=2,
    )
    ledger = HostOwnedPromptAccountingLedger(
        model_context_window=100000,
        breakdown=HostOwnedBreakdown(system_prompt_tokens=10000),
        safety_reserve_tokens=10000,
    )
    # effective_capacity = 80000 -> high_threshold = 64000, low_target = 40000
    decision = controller.evaluate(
        current_compactable_tokens=68000,
        current_turn=5,
        ledger=ledger,
    )

    assert decision.should_compact
    assert decision.trigger_mode == CompactionTriggerMode.HIGH_WATERMARK
    assert decision.high_watermark_tokens == 64000
    assert decision.target_low_watermark_tokens == 40000
    assert decision.tokens_to_reduce == 28000


def test_hysteresis_buffer_deadband_suppression() -> None:
    """Verify deadband prevents micro-compaction when token reduction delta is too small."""
    controller = CompactionHysteresisBufferController(
        high_watermark_ratio=0.80,
        low_watermark_ratio=0.75,  # narrow band
        min_reduction_tokens=3000,
        cooldown_turns=2,
    )
    ledger = HostOwnedPromptAccountingLedger(
        model_context_window=100000,
        breakdown=HostOwnedBreakdown(),
        safety_reserve_tokens=0,
    )
    # effective_capacity = 100000 -> high = 80000, low = 75000
    # current = 81000 -> over_low = 6000, but let's test current = 80500 with min_reduction 6000
    controller.min_reduction_tokens = 6000
    decision = controller.evaluate(
        current_compactable_tokens=80500,
        current_turn=10,
        ledger=ledger,
    )

    # tokens_over_low = 5500 < 6000 -> suppressed by deadband
    assert not decision.should_compact
    assert "deadband threshold" in decision.reason


def test_hysteresis_buffer_cooldown_and_emergency_bypass() -> None:
    """Verify cooldown prevents fluttering and emergency overflow bypasses cooldown."""
    controller = CompactionHysteresisBufferController(
        high_watermark_ratio=0.80,
        low_watermark_ratio=0.50,
        min_reduction_tokens=2000,
        cooldown_turns=3,
        last_compaction_turn=5,
    )
    ledger = HostOwnedPromptAccountingLedger(
        model_context_window=100000,
        breakdown=HostOwnedBreakdown(),
        safety_reserve_tokens=0,
    )

    # Turn 6 is within cooldown (5 + 3 = 8 is first allowed turn)
    decision = controller.evaluate(
        current_compactable_tokens=85000,
        current_turn=6,
        ledger=ledger,
    )
    assert not decision.should_compact
    assert decision.in_cooldown
    assert decision.cooldown_remaining_turns == 2

    # Emergency overflow forces bypass
    emergency_decision = controller.evaluate(
        current_compactable_tokens=85000,
        current_turn=6,
        ledger=ledger,
        force_emergency=True,
    )
    assert emergency_decision.should_compact
    assert emergency_decision.trigger_mode == CompactionTriggerMode.EMERGENCY_OVERFLOW


def test_compaction_observation_collector_payload_and_frames() -> None:
    """Verify retained frame classification and comprehensive telemetry payload generation."""
    tool_call = ToolCall(name="view_file", args={"path": "main.py"}, id="call-1")
    retained_messages = [
        SystemMessage(content="System prompt anchor"),
        HumanMessage(content="Previous checkpoint summary: [previous-summary] Initialized task."),
        AIMessage(content="I will read main.py", tool_calls=[tool_call]),
        ToolMessage(content="File contents: print('hello')", tool_call_id="call-1"),
        HumanMessage(content="Now refactor this function please."),
    ]

    ledger = HostOwnedPromptAccountingLedger(
        model_context_window=100000,
        breakdown=HostOwnedBreakdown(
            system_prompt_tokens=2500,
            tool_schemas_tokens=3500,
        ),
        safety_reserve_tokens=4000,
    )

    payload = CompactionObservationCollector.create_observation_payload(
        session_id="session-xyz-123",
        trigger_mode=CompactionTriggerMode.HIGH_WATERMARK,
        tokens_before=85000,
        tokens_after=32000,
        duration_ms=452.8,
        ledger=ledger,
        archived_message_count=18,
        retained_messages=retained_messages,
    )

    assert payload.session_id == "session-xyz-123"
    assert payload.tokens_before == 85000
    assert payload.tokens_after == 32000
    assert payload.tokens_saved == 53000
    assert payload.compression_ratio_pct == 62.35
    assert payload.archived_message_count == 18
    assert len(payload.retained_frames) == 5

    # Check frame categories
    frames = payload.retained_frames
    assert frames[0].category == FrameCategory.SYSTEM_ANCHOR
    assert frames[1].category == FrameCategory.CHECKPOINT_SUMMARY
    assert frames[2].category == FrameCategory.TOOL_PAIRING
    assert frames[3].category == FrameCategory.TOOL_PAIRING
    assert frames[4].category == FrameCategory.ACTIVE_TURN

    # Check dictionary serialization
    p_dict = payload.to_dict()
    assert p_dict["trigger_mode"] == "high_watermark"
    assert p_dict["tokens_saved"] == 53000
    assert isinstance(p_dict["retained_frames"], list)
    assert len(p_dict["retained_frames"]) == 5
    assert p_dict["retained_frames"][0]["category"] == "system_anchor"
