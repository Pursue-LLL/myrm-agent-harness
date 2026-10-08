# [INPUT]: AgentThoughtNormalizer, AgentThoughtStreamAdapterAndExternalClientDualModeEventBridgeSuite, AgentThoughtStreamAdapterSuite, ClientCapabilityNegotiator, ClientReasoningMode, LongReasoningHeartbeatConduit, ThoughtActionType, ThoughtAdapterConfig, ThoughtStepDescriptor, ThoughtStreamChunk
# [OUTPUT]: test_agent_thought_stream_adapter_suite.py
# [POS]: tests/agent/context_management/test_agent_thought_stream_adapter_suite.py

"""Comprehensive unit tests for AgentThoughtStreamAdapterAndExternalClientDualModeEventBridgeSuite.

Verifies:
1. Client capability negotiation: explicit headers, capability flags, request parameters, and user-agent heuristics.
2. Normalization: structured headers for thoughts, tools, observations, and tool payload truncation.
3. Native reasoning mode: streaming thinking/tool steps exclusively via delta.reasoning_content.
4. Think tag fallback mode: stateful <think>...</think> wrapping via delta.content with automatic safe closure.
5. Silent mode: complete suppression of internal intermediate events while preserving final content.
6. Long-reasoning keep-alive conduit: threshold-based heartbeat generation and zero-pollution SSE comments.
7. End-to-end facade lifecycle and full alias parity.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.thought_stream_adapter import (
    AgentThoughtNormalizer,
    AgentThoughtStreamAdapterAndExternalClientDualModeEventBridgeSuite,
    AgentThoughtStreamAdapterSuite,
    ClientCapabilityNegotiator,
    ClientReasoningMode,
    LongReasoningHeartbeatConduit,
    ThoughtActionType,
    ThoughtAdapterConfig,
    ThoughtStepDescriptor,
    ThoughtStreamChunk,
)


def test_client_capability_negotiation() -> None:
    """Verifies priority resolution across headers, parameters, and user-agents."""
    config = ThoughtAdapterConfig(default_mode=ClientReasoningMode.REASONING_CONTENT)
    negotiator = ClientCapabilityNegotiator(config)

    # 1. Header override takes highest precedence
    mode = negotiator.negotiate(
        user_agent="Open-WebUI/0.3.0",
        headers={"X-Reasoning-Mode": "silent"},
        request_params={"return_thinking": True},
    )
    assert mode == ClientReasoningMode.SILENT

    mode_tag = negotiator.negotiate(
        headers={"X-Reasoning-Mode": "think_tag_fallback"},
    )
    assert mode_tag == ClientReasoningMode.THINK_TAG_FALLBACK

    # 2. Client capability header
    mode_cap = negotiator.negotiate(
        headers={"X-Client-Capability": "reasoning_content,markdown"},
    )
    assert mode_cap == ClientReasoningMode.REASONING_CONTENT

    # 3. Request parameters
    mode_silent_param = negotiator.negotiate(
        request_params={"stream_reasoning": False},
    )
    assert mode_silent_param == ClientReasoningMode.SILENT

    mode_effort = negotiator.negotiate(
        request_params={"reasoning_effort": "high"},
    )
    assert mode_effort == ClientReasoningMode.REASONING_CONTENT

    mode_thinking = negotiator.negotiate(
        request_params={"return_thinking": True},
    )
    assert mode_thinking == ClientReasoningMode.REASONING_CONTENT

    # 4. User-Agent heuristic
    mode_webui = negotiator.negotiate(user_agent="Mozilla/5.0 OpenWebUI/1.2")
    assert mode_webui == ClientReasoningMode.REASONING_CONTENT

    mode_librechat = negotiator.negotiate(user_agent="LibreChat/0.7.0")
    assert mode_librechat == ClientReasoningMode.REASONING_CONTENT

    mode_curl = negotiator.negotiate(user_agent="curl/7.88.1")
    assert mode_curl == ClientReasoningMode.THINK_TAG_FALLBACK

    mode_requests = negotiator.negotiate(user_agent="python-requests/2.31.0")
    assert mode_requests == ClientReasoningMode.THINK_TAG_FALLBACK

    # 5. Default fallback
    mode_unknown = negotiator.negotiate(user_agent="CustomAgentRunner/1.0")
    assert mode_unknown == ClientReasoningMode.REASONING_CONTENT


def test_thought_normalizer_formatting_and_summary() -> None:
    """Verifies action headers, elapsed time tracking, and verbose payload truncation."""
    config = ThoughtAdapterConfig(max_tool_summary_chars=50)
    normalizer = AgentThoughtNormalizer(config)

    # Record step start and verify elapsed time calculation
    t0 = 100.0
    normalizer.record_step_start("step-1", start_time=t0)
    elapsed = normalizer.get_elapsed_ms("step-1", finish_time=100.125)
    assert pytest.approx(elapsed, 0.1) == 125.0

    # Test headers for diverse actions
    step_think = ThoughtStepDescriptor(
        step_id="step-1",
        action_type=ThoughtActionType.THINKING,
        title="Analyzing repository structure",
    )
    header_think = normalizer.format_step_header(step_think)
    assert "> 💭 [Thinking] Analyzing repository structure" in header_think

    step_tool = ThoughtStepDescriptor(
        step_id="step-2",
        action_type=ThoughtActionType.TOOL_EXECUTION,
        title="Execute bash command",
        metadata={"tool_name": "bash"},
    )
    header_tool = normalizer.format_step_header(step_tool)
    assert "> 🛠️ [Tool Call] Execute bash command (bash)" in header_tool

    # Test step completion summary
    completion = normalizer.format_step_completion(
        step_tool,
        status="completed",
        summary="Found 12 matching test files in tests/",
        elapsed_ms=150.0,
    )
    assert "> ✓ [COMPLETED] Finished in 150.0ms" in completion
    assert "> Outcome: Found 12 matching test files in tests/" in completion

    # Test payload truncation
    long_payload = "a" * 120
    truncated = normalizer.truncate_tool_payload(long_payload)
    assert len(truncated) < 120
    assert "... (truncated, total 120 chars)" in truncated


def test_reasoning_content_mode_streaming() -> None:
    """Verifies modern reasoning_content mode streaming semantics."""
    suite = AgentThoughtStreamAdapterSuite(initial_mode=ClientReasoningMode.REASONING_CONTENT)
    assert suite.active_mode == ClientReasoningMode.REASONING_CONTENT

    # 1. Start step
    chunks_start = suite.start_step(
        step_id="s1",
        action_type=ThoughtActionType.THINKING,
        title="Evaluating query intent",
    )
    assert len(chunks_start) == 1
    assert chunks_start[0].chunk_type == "reasoning_content"
    assert "Evaluating query intent" in chunks_start[0].text

    # 2. Stream incremental thinking tokens
    chunks_delta = suite.stream_step_chunk("s1", "User wants a unit test.")
    assert len(chunks_delta) == 1
    assert chunks_delta[0].chunk_type == "reasoning_content"
    assert chunks_delta[0].text == "User wants a unit test."

    # 3. Finish step
    chunks_finish = suite.finish_step("s1", status="completed", summary="Plan established", elapsed_ms=45.0)
    assert len(chunks_finish) == 1
    assert chunks_finish[0].chunk_type == "reasoning_content"
    assert "Plan established" in chunks_finish[0].text

    # 4. Stream final content - zero reasoning tags leaked into content
    chunks_final = suite.stream_final_content_chunk("Here is the requested solution:")
    assert len(chunks_final) == 1
    assert chunks_final[0].chunk_type == "content"
    assert "<think>" not in chunks_final[0].text
    assert chunks_final[0].text == "Here is the requested solution:"

    # 5. Close stream
    chunks_close = suite.close_stream()
    assert len(chunks_close) == 1
    assert chunks_close[0].chunk_type == "finish"


def test_think_tag_fallback_mode_streaming() -> None:
    """Verifies legacy think_tag_fallback mode with stateful tag injection and automatic closure."""
    suite = AgentThoughtStreamAdapterSuite(initial_mode=ClientReasoningMode.THINK_TAG_FALLBACK)
    assert suite.active_mode == ClientReasoningMode.THINK_TAG_FALLBACK

    # 1. Start step: must inject <think>\n first, followed by header chunk
    chunks_start = suite.start_step(
        step_id="step-legacy",
        action_type=ThoughtActionType.PLANNING,
        title="Formulating multi-step execution",
    )
    assert len(chunks_start) == 2
    assert chunks_start[0].chunk_type == "content"
    assert chunks_start[0].text == "<think>\n"
    assert chunks_start[1].chunk_type == "content"
    assert "Formulating multi-step execution" in chunks_start[1].text
    assert suite.is_think_tag_open is True

    # 2. Second step while tag is open: does NOT duplicate <think> tag
    chunks_substep = suite.start_step(
        step_id="step-sub",
        action_type=ThoughtActionType.TOOL_EXECUTION,
        title="Reading workspace file",
    )
    assert len(chunks_substep) == 1
    assert chunks_substep[0].chunk_type == "content"
    assert "Reading workspace file" in chunks_substep[0].text

    # 3. Finish steps
    suite.finish_step("step-sub", status="completed")
    suite.finish_step("step-legacy", status="completed")
    assert suite.is_think_tag_open is True

    # 4. Transition to final content: automatically closes </think> tag
    chunks_final = suite.stream_final_content_chunk("Final answer for legacy client.")
    assert len(chunks_final) == 2
    assert chunks_final[0].chunk_type == "content"
    assert chunks_final[0].text == "\n</think>\n"
    assert suite.is_think_tag_open is False
    assert chunks_final[1].chunk_type == "content"
    assert chunks_final[1].text == "Final answer for legacy client."


def test_silent_mode_streaming() -> None:
    """Verifies complete suppression of thought/tool steps in silent mode."""
    suite = AgentThoughtStreamAdapterSuite(initial_mode=ClientReasoningMode.SILENT)

    # All thought steps should produce zero chunks
    chunks_start = suite.start_step("s1", ThoughtActionType.THINKING, "Quiet thinking")
    assert chunks_start == []

    chunks_delta = suite.stream_step_chunk("s1", "internal note")
    assert chunks_delta == []

    chunks_finish = suite.finish_step("s1", status="completed")
    assert chunks_finish == []

    # Final content is delivered cleanly
    chunks_final = suite.stream_final_content_chunk("Concise response.")
    assert len(chunks_final) == 1
    assert chunks_final[0].chunk_type == "content"
    assert chunks_final[0].text == "Concise response."


def test_long_reasoning_heartbeat_conduit() -> None:
    """Verifies keep-alive heartbeat generation and zero content pollution."""
    config = ThoughtAdapterConfig(heartbeat_interval_seconds=1.5, enable_heartbeat=True)
    conduit = LongReasoningHeartbeatConduit(config)

    t0 = 1000.0
    conduit.mark_activity(t0)

    # Silence of 1.0s: threshold (1.5s) not met
    assert conduit.should_emit_heartbeat(now=t0 + 1.0) is False

    # Silence of 1.6s: threshold met
    assert conduit.should_emit_heartbeat(now=t0 + 1.6) is True

    # 1. Heartbeat under REASONING_CONTENT mode produces subtle reasoning chunk
    hb_reasoning = conduit.generate_heartbeat_chunk(
        mode=ClientReasoningMode.REASONING_CONTENT,
        active_step_title="Running sandbox suite",
        now=t0 + 1.6,
    )
    assert hb_reasoning.is_heartbeat is True
    assert hb_reasoning.chunk_type == "reasoning_content"
    assert hb_reasoning.text == " ."

    # Generating heartbeat refreshes activity
    assert conduit.should_emit_heartbeat(now=t0 + 1.7) is False

    # 2. Heartbeat under THINK_TAG_FALLBACK and SILENT mode produces SSE comment line
    hb_comment = conduit.generate_heartbeat_chunk(
        mode=ClientReasoningMode.THINK_TAG_FALLBACK,
        active_step_title="Downloading model weights",
        now=t0 + 3.5,
    )
    assert hb_comment.is_heartbeat is True
    assert hb_comment.chunk_type == "comment"
    assert hb_comment.text.startswith(": keep-alive")
    assert "Downloading model weights" in hb_comment.text


def test_facade_end_to_end_orchestration_and_alias_parity() -> None:
    """Verifies end-to-end lifecycle orchestration and complete alias equality."""
    # Test parity between short name and full roadmap alias
    assert AgentThoughtStreamAdapterAndExternalClientDualModeEventBridgeSuite is AgentThoughtStreamAdapterSuite

    suite = AgentThoughtStreamAdapterAndExternalClientDualModeEventBridgeSuite()

    # Dynamic client negotiation
    mode = suite.negotiate_client_mode(user_agent="Open-WebUI/0.4.0")
    assert mode == ClientReasoningMode.REASONING_CONTENT

    # Multi-step execution
    suite.start_step("st1", ThoughtActionType.PLANNING, "Plan phase")
    suite.stream_step_chunk("st1", "Drafting approach.")
    suite.finish_step("st1", status="completed", summary="Ready")

    # Polling heartbeat when no timeout
    hb = suite.poll_heartbeat()
    assert hb is None

    # Delivery of final answer and closure
    content_chunks = suite.stream_final_content_chunk("Here is your result.")
    assert len(content_chunks) == 1
    assert content_chunks[0].text == "Here is your result."

    finish_chunks = suite.close_stream()
    assert len(finish_chunks) == 1
    assert finish_chunks[0].chunk_type == "finish"
