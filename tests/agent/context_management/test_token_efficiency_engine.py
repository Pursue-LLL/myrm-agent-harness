"""Tests for Provider Usage Anchoring and Negative Routing Token Efficiency Suite (Item 229)."""

import pytest

from myrm_agent_harness.agent.context_management.token_efficiency import (
    NegativeRouteDecision,
    NegativeRouteRule,
    ProviderUsageAnchor,
    TokenEfficiencyConfig,
    TokenEfficiencyGovernorEngine,
    TokenEfficiencyLedger,
)


def test_provider_usage_anchor_sync_and_incremental_calculation() -> None:
    """Verify authoritative Provider usage anchor eliminates drift by computing solely incremental tokens."""
    engine = TokenEfficiencyGovernorEngine(TokenEfficiencyConfig(bytes_per_token_estimate=4.0))
    session_id = "sess-anchor-eval-01"

    base_last_message = "Here is the summary of the architectural analysis so far."
    # Provider reports exact authoritative prompt_tokens from API response
    anchor = engine.record_provider_anchor(
        session_id=session_id,
        prompt_tokens=4500,
        last_message_content=base_last_message,
        turn_index=3,
    )

    assert anchor.session_id == session_id
    assert anchor.prompt_tokens == 4500
    assert len(anchor.last_message_fingerprint) == 16

    # Subsequent turn sends 2 incremental messages totaling 400 characters (100 tokens)
    incremental_messages = [
        {"role": "user", "content": "x" * 200},
        {"role": "assistant", "content": "y" * 200},
    ]

    total_tokens = engine.calculate_anchored_context_tokens(
        session_id=session_id,
        incremental_messages=incremental_messages,
        base_message_content=base_last_message,
    )

    # 4500 anchor + (400 chars / 4.0) = 4500 + 100 = 4600
    assert total_tokens == 4600

    # Fingerprint mismatch scenario: falls back to full estimate
    mismatched_base = "Modified or corrupted base message text."
    fallback_tokens = engine.calculate_anchored_context_tokens(
        session_id=session_id,
        incremental_messages=incremental_messages,
        base_message_content=mismatched_base,
    )
    # Expected fallback uses character heuristic across all text
    assert fallback_tokens != 4600


def test_negative_routing_zero_ms_interception() -> None:
    """Verify skills with matching NOT FOR rules are intercepted at 0ms, preventing false-lane tool calls."""
    engine = TokenEfficiencyGovernorEngine(
        TokenEfficiencyConfig(fallback_negative_route_penalty=1500)
    )
    session_id = "sess-negative-route"

    rules = [
        NegativeRouteRule(
            skill_id="heavy_repo_refactor_skill",
            not_for_patterns=["语法问答", "简单问答", "no_repo"],
            rejection_reason="Not suited for purely conceptual language QA without an open repository.",
        ),
        NegativeRouteRule(
            skill_id="docker_cluster_deploy_skill",
            not_for_patterns=["前端调试", "css"],
            rejection_reason="Not suited for UI cosmetic changes.",
        ),
    ]

    candidates = ["heavy_repo_refactor_skill", "general_knowledge_skill", "docker_cluster_deploy_skill"]
    user_intent = "请为我进行 Python pass 语句的简单问答解释"

    allowed, decisions = engine.evaluate_negative_routes(
        session_id=session_id,
        user_intent=user_intent,
        candidate_skills=candidates,
        rules=rules,
    )

    # heavy_repo_refactor_skill must be blocked because user_intent matches "简单问答"
    assert "heavy_repo_refactor_skill" not in allowed
    assert "general_knowledge_skill" in allowed
    assert "docker_cluster_deploy_skill" in allowed

    blocked_decisions = [d for d in decisions if d.is_blocked]
    assert len(blocked_decisions) == 1
    assert blocked_decisions[0].skill_id == "heavy_repo_refactor_skill"
    assert blocked_decisions[0].matched_pattern == "简单问答"

    # Ledger must register the interception and token savings estimate
    ledger = engine.get_ledger(session_id)
    assert ledger.negative_routes_intercepted == 1
    assert ledger.estimated_tokens_saved == 1500


def test_heterogeneous_reasoning_seal_stripping() -> None:
    """Verify incompatible reasoning seals are seamlessly stripped when switching model providers."""
    engine = TokenEfficiencyGovernorEngine()
    session_id = "sess-cross-provider-switch"

    messages = [
        {"role": "system", "content": "You are a coding assistant."},
        {
            "role": "assistant",
            "content": (
                'Analysis done. [encrypted_reasoning issuer="openai_codex"]8a9fbc9081e7d2[/encrypted_reasoning]'
                " Here is the fix."
            ),
        },
    ]

    # Switching to Anthropic: openai_codex seal must be stripped to prevent HTTP 400
    sanitized, stripped_count = engine.strip_incompatible_reasoning_seals(
        session_id=session_id,
        messages=messages,
        target_provider="anthropic",
    )

    assert stripped_count == 1
    assert "[encrypted_reasoning" not in sanitized[1]["content"]
    assert "Analysis done." in sanitized[1]["content"]
    assert "Here is the fix." in sanitized[1]["content"]

    # Re-testing with matching provider: seal is safely preserved
    preserved, stripped_zero = engine.strip_incompatible_reasoning_seals(
        session_id=session_id,
        messages=messages,
        target_provider="openai_codex",
    )
    assert stripped_zero == 0
    assert "[encrypted_reasoning" in preserved[1]["content"]


def test_token_efficiency_ledger_observability() -> None:
    """Verify complete ledger tracks sync events, interceptions, and seal stripping accurately."""
    engine = TokenEfficiencyGovernorEngine()
    session_id = "sess-ledger-summary"

    # 1. Sync an anchor
    engine.record_provider_anchor(session_id, 3200, "Base msg", 1)

    # 2. Trigger a negative route block
    engine.evaluate_negative_routes(
        session_id=session_id,
        user_intent="simple query no_repo",
        candidate_skills=["tool_heavy"],
        rules=[NegativeRouteRule("tool_heavy", ["no_repo"], "Requires repository")],
    )

    # 3. Strip a seal
    msgs = [{"role": "assistant", "content": 'msg [encrypted_reasoning issuer="x"]seal[/encrypted_reasoning]'}]
    engine.strip_incompatible_reasoning_seals(session_id, msgs, "y")

    ledger: TokenEfficiencyLedger = engine.get_ledger(session_id)
    assert ledger.session_id == session_id
    assert ledger.total_anchor_syncs == 1
    assert ledger.negative_routes_intercepted == 1
    assert ledger.seals_stripped == 1
    assert ledger.estimated_tokens_saved > 0
