# ============================================================================
# Unit Tests: System Prompt Static Prefix Anchoring & Tail Redirector (Item 168)
# ============================================================================

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.agent.context_management.prompt_anchoring import (
    EphemeralRuntimeMetadata,
    StaticAnchorBlueprint,
    SystemPromptAnchoringGateway,
)


def _sample_static_blueprint() -> StaticAnchorBlueprint:
    return StaticAnchorBlueprint(
        system_instructions="You are an autonomous AI software engineer.",
        safety_guidelines="Never execute destructive commands outside sandbox.",
        tool_protocols="Always verify tool parameters using strictly typed JSON schema.",
        domain_knowledge="Enterprise microservices architecture with gRPC and HTTP/2.",
    )


def test_dual_layer_prompt_assembly_and_token_estimation() -> None:
    """Test clean separation of Layer A static anchor and Layer B ephemeral tail."""
    gateway = SystemPromptAnchoringGateway()
    blueprint = _sample_static_blueprint()
    meta = EphemeralRuntimeMetadata(
        timestamp_iso="2026-10-08T01:58:00Z",
        timezone_name="UTC",
        session_id="session-anchor-100",
        workspace_cwd="/home/agent/workspace",
    )

    bundle = gateway.build_anchored_prompt(blueprint, meta, redirect_to_user_tail=True)

    # When redirected to user tail, System prompt must NOT contain dynamic timestamp or session_id
    assert "2026-10-08T01:58:00Z" not in bundle.combined_system_prompt
    assert "session-anchor-100" not in bundle.combined_system_prompt
    assert bundle.combined_system_prompt == bundle.layer_a_static_prefix
    assert len(bundle.layer_a_sha256) == 64
    assert bundle.prefix_tokens_estimate > 0

    # Layer B contains structured environment XML
    assert "<ephemeral_runtime_environment>" in bundle.layer_b_tail_injection
    assert "session-anchor-100" in bundle.layer_b_tail_injection


def test_temporal_drift_invariance_verification() -> None:
    """Test that time advancing by hours/days causes ZERO drift in static prefix cache."""
    gateway = SystemPromptAnchoringGateway()
    blueprint = _sample_static_blueprint()

    # Turn 1: 08:00
    meta_turn1 = EphemeralRuntimeMetadata(
        timestamp_iso="2026-10-08T08:00:00Z",
        timezone_name="UTC",
        session_id="session-drift-test",
        workspace_cwd="/app/code",
    )
    bundle_1 = gateway.build_anchored_prompt(blueprint, meta_turn1)

    # Turn 2: 12:30 (4.5 hours later)
    meta_turn2 = EphemeralRuntimeMetadata(
        timestamp_iso="2026-10-08T12:30:00Z",
        timezone_name="UTC",
        session_id="session-drift-test",
        workspace_cwd="/app/code",
    )
    bundle_2 = gateway.build_anchored_prompt(blueprint, meta_turn2)

    # Verify invariance
    report = gateway.verify_prefix_invariance(bundle_1, bundle_2)

    assert report.is_prefix_stable is True
    assert report.drift_detected_in_static is False
    assert report.ephemeral_tail_changed is True
    assert bundle_1.layer_a_sha256 == bundle_2.layer_a_sha256
    assert bundle_1.layer_b_sha256 != bundle_2.layer_b_sha256


def test_static_blueprint_modification_detected_as_drift() -> None:
    """Test that deliberate changes to Layer A are immediately identified as cache drift."""
    gateway = SystemPromptAnchoringGateway()
    b1 = _sample_static_blueprint()
    b2 = StaticAnchorBlueprint(
        system_instructions=b1.system_instructions,
        safety_guidelines="Altered safety protocol rule.",  # modified
        tool_protocols=b1.tool_protocols,
        domain_knowledge=b1.domain_knowledge,
    )

    meta = EphemeralRuntimeMetadata(
        timestamp_iso="2026-10-08T00:00:00Z",
        timezone_name="UTC",
        session_id="sess-mod",
        workspace_cwd="/app",
    )

    bundle_1 = gateway.build_anchored_prompt(b1, meta)
    bundle_2 = gateway.build_anchored_prompt(b2, meta)

    report = gateway.verify_prefix_invariance(bundle_1, bundle_2)
    assert report.is_prefix_stable is False
    assert report.drift_detected_in_static is True
    assert "CRITICAL: Static Layer A prefix hash altered!" in report.diagnostic_notes


def test_inject_into_messages_tail_redirection() -> None:
    """Test injecting anchored SystemMessage at index 0 and redirecting Layer B to user tail."""
    gateway = SystemPromptAnchoringGateway()
    blueprint = _sample_static_blueprint()
    meta = EphemeralRuntimeMetadata(
        timestamp_iso="2026-10-08T02:00:00Z",
        timezone_name="UTC",
        session_id="session-msg-inject",
        workspace_cwd="/root/proj",
    )

    bundle = gateway.build_anchored_prompt(blueprint, meta, redirect_to_user_tail=True)

    input_messages = [
        HumanMessage(content="Please review this function implementation.")
    ]

    injected = gateway.inject_into_messages(input_messages, bundle)

    assert len(injected) == 2
    # Message 0: Pristine System Message
    assert isinstance(injected[0], SystemMessage)
    assert injected[0].content == bundle.layer_a_static_prefix
    assert "2026-10-08T02:00:00Z" not in injected[0].content

    # Message 1: Human Message with tail XML environment appended
    assert isinstance(injected[1], HumanMessage)
    assert "Please review this function implementation." in injected[1].content
    assert "<ephemeral_runtime_environment>" in injected[1].content
    assert "2026-10-08T02:00:00Z" in injected[1].content


def test_fallback_mode_layer_b_appended_to_system_tail() -> None:
    """Test fallback mode where Layer B is appended at the very end of SystemMessage."""
    gateway = SystemPromptAnchoringGateway()
    blueprint = _sample_static_blueprint()
    meta = EphemeralRuntimeMetadata(
        timestamp_iso="2026-10-08T03:00:00Z",
        timezone_name="UTC",
        session_id="session-fallback",
        workspace_cwd="/var/log",
    )

    bundle = gateway.build_anchored_prompt(blueprint, meta, redirect_to_user_tail=False)

    # Starts with Layer A static text
    assert bundle.combined_system_prompt.startswith(bundle.layer_a_static_prefix)
    # Ends with Layer B XML context
    assert bundle.combined_system_prompt.endswith("</ephemeral_runtime_environment>")
