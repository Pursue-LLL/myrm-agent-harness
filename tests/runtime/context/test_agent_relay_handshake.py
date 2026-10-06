"""Unit tests for Heterogeneous Agent Context Handshake & Relay Protocol Bridge (Item 33)."""

from myrm_agent_harness.runtime.context.agent_relay_handshake import (
    AgentProfileDescriptor,
    AgentRelayHandshakeBridge,
    AgentRelayPacketBuilder,
    ContextBudgetAdaptiveAligner,
    HandshakeResult,
    RelayStatePayload,
)
from myrm_agent_harness.utils.text_utils import get_token_count


def test_create_relay_packet_payload() -> None:
    """Verifies building a standardized intermediate representation of in-flight work."""
    source_agent = AgentProfileDescriptor(
        agent_id="claude_architect_1",
        model_name="claude-3-7-sonnet",
        vendor="anthropic",
        context_window_tokens=200000,
        specialties=["macro_planning", "architecture"],
    )
    target_agent = AgentProfileDescriptor(
        agent_id="codex_implementer_1",
        model_name="gpt-4o-mini",
        vendor="openai",
        context_window_tokens=128000,
        specialties=["implementation", "code_completion"],
    )

    payload: RelayStatePayload = AgentRelayPacketBuilder.create_payload(
        source_agent=source_agent,
        target_agent=target_agent,
        session_id="sess_migration_099",
        task_objective="Refactor authentication layer to JWT with refresh tokens",
        pending_goal="Implement token rotation in app/services/auth.py",
        recent_file_modifications=["app/database/models/user.py", "app/schemas/auth.py"],
        key_artifacts_produced=["art_jwt_spec_v1"],
        technical_conclusions=[
            "Store refresh token in HTTP-only cookie",
            "Use RS256 asymmetric signing keys",
        ],
        active_blockers=["Need RS256 key pair generator utility"],
        distilled_summary="Architectural schema completed; ready for implementation phase.",
    )

    assert payload.relay_id.startswith("relay_")
    assert payload.session_id == "sess_migration_099"
    assert payload.source_agent.agent_id == "claude_architect_1"
    assert payload.target_agent.agent_id == "codex_implementer_1"
    assert len(payload.recent_file_modifications) == 2
    assert len(payload.technical_conclusions) == 2
    assert len(payload.active_blockers) == 1
    assert payload.created_at_iso != ""


def test_context_budget_adaptive_calculation() -> None:
    """Verifies calculation of safe token budgets across heterogeneous window sizes."""
    # 1. Very small window (e.g. 8K) -> bounded by lower floor of 500
    small_agent = AgentProfileDescriptor(
        agent_id="small_agent",
        model_name="legacy-model",
        vendor="custom",
        context_window_tokens=4000,
    )
    assert ContextBudgetAdaptiveAligner.calculate_safe_budget(small_agent) == 500

    # 2. Medium window (32K) -> 32000 * 0.08 = 2560
    medium_agent = AgentProfileDescriptor(
        agent_id="med_agent",
        model_name="deepseek-coder",
        vendor="deepseek",
        context_window_tokens=32000,
    )
    assert ContextBudgetAdaptiveAligner.calculate_safe_budget(medium_agent) == 2560

    # 3. Massive window (200K) -> capped at upper ceiling of 3500
    large_agent = AgentProfileDescriptor(
        agent_id="large_agent",
        model_name="claude-3-opus",
        vendor="anthropic",
        context_window_tokens=200000,
    )
    assert ContextBudgetAdaptiveAligner.calculate_safe_budget(large_agent) == 3500


def test_execute_handshake_success() -> None:
    """Verifies executing a seamless context handshake generating handover XML prompt block."""
    source_agent = AgentProfileDescriptor(
        agent_id="agent_planner",
        model_name="claude-3-7-sonnet",
        vendor="anthropic",
        context_window_tokens=200000,
    )
    target_agent = AgentProfileDescriptor(
        agent_id="agent_coder",
        model_name="codex-5",
        vendor="openai",
        context_window_tokens=128000,
    )

    payload = AgentRelayPacketBuilder.create_payload(
        source_agent=source_agent,
        target_agent=target_agent,
        session_id="sess_feature_77",
        task_objective="Implement payment gateway webhook handler",
        pending_goal="Write unit tests verifying HMAC signature validation",
        recent_file_modifications=["services/payment/webhook.py"],
        technical_conclusions=["Use constant-time string comparison for signatures"],
        active_blockers=[],
        distilled_summary="Webhook handler structure done.",
    )

    bridge = AgentRelayHandshakeBridge()
    result: HandshakeResult = bridge.execute_handshake(payload)

    assert result.status == "success"
    assert result.source_agent_id == "agent_planner"
    assert result.target_agent_id == "agent_coder"
    assert not result.is_compressed
    assert result.context_tokens_consumed > 0

    # Validate XML prompt contents
    prompt = result.injected_context_prompt
    assert '<agent_relay_handoff mode="seamless_continuation">' in prompt
    assert '<source_agent id="agent_planner"' in prompt
    assert '<target_agent id="agent_coder"' in prompt
    assert "<task_objective>Implement payment gateway webhook handler</task_objective>" in prompt
    assert "<pending_goal>Write unit tests verifying HMAC signature validation</pending_goal>" in prompt
    assert "<file>services/payment/webhook.py</file>" in prompt
    assert "<item>Use constant-time string comparison for signatures</item>" in prompt
    assert "You are inheriting this work session directly from the source agent" in prompt
    assert "</agent_relay_handoff>" in prompt


def test_handshake_budget_compression_guard() -> None:
    """Verifies automatic compression and truncation when payload exceeds target agent budget."""
    source_agent = AgentProfileDescriptor(
        agent_id="heavy_agent",
        model_name="claude-large",
        vendor="anthropic",
        context_window_tokens=200000,
    )
    # Target agent with very tight window
    tight_target = AgentProfileDescriptor(
        agent_id="tight_agent",
        model_name="embedded-3k",
        vendor="local",
        context_window_tokens=6000,  # 8% of 6000 = 480 -> lower bounded to 500 tokens
    )

    massive_summary = "CRITICAL DIAGNOSTICS: " + ("Log trace info pattern. " * 300)

    payload = AgentRelayPacketBuilder.create_payload(
        source_agent=source_agent,
        target_agent=tight_target,
        session_id="sess_heavy_01",
        task_objective="Massive distributed log analysis",
        pending_goal="Find memory exhaustion trigger",
        distilled_summary=massive_summary,
    )

    bridge = AgentRelayHandshakeBridge()
    result: HandshakeResult = bridge.execute_handshake(payload)

    assert result.status == "success"
    assert result.is_compressed
    assert "Prior context condensed to align with target agent window budget" in result.injected_context_prompt

    budget = ContextBudgetAdaptiveAligner.calculate_safe_budget(tight_target)
    consumed_tokens = get_token_count(result.injected_context_prompt)
    assert consumed_tokens <= budget + 50
