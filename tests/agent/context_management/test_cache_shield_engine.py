"""Tests for Prompt Cache Break Prevention Shield & Session Branching Suite (Item 240)."""

from myrm_agent_harness.agent.context_management.cache_shield import (
    CacheBreakEvaluation,
    CacheBreakPreventionShieldEngine,
    CacheParameterKind,
    CachePreservingForkResult,
    CacheRewindResult,
    CacheRiskLevel,
    evaluate_parameter_mutation,
)


def test_parameter_mutation_cache_break_evaluation() -> None:
    """Verify interception of model and thinking effort mutations destroying prompt cache."""
    # 1. No mutation -> SAFE
    safe_eval = evaluate_parameter_mutation(
        param_kind=CacheParameterKind.MODEL,
        old_value="claude-3-7-sonnet",
        new_value="claude-3-7-sonnet",
        current_tokens=15000,
    )
    assert safe_eval.risk_level == CacheRiskLevel.SAFE
    assert not safe_eval.is_blocking_alert
    assert safe_eval.cached_tokens_at_risk == 0

    # 2. Short session under threshold (3,000 tokens) -> LOW risk, allow in-place
    low_eval = evaluate_parameter_mutation(
        param_kind=CacheParameterKind.MODEL,
        old_value="claude-3-7-sonnet",
        new_value="gpt-4o",
        current_tokens=3000,
        cache_alert_threshold=8000,
    )
    assert low_eval.risk_level == CacheRiskLevel.LOW
    assert not low_eval.is_blocking_alert
    assert low_eval.recommended_action == "apply_in_place"

    # 3. Long session (18,000 tokens) model switch -> HIGH risk, 10.0x cost penalty
    high_eval = evaluate_parameter_mutation(
        param_kind=CacheParameterKind.MODEL,
        old_value="claude-3-7-sonnet",
        new_value="gpt-4o",
        current_tokens=18000,
        cache_alert_threshold=8000,
    )
    assert high_eval.risk_level == CacheRiskLevel.HIGH
    assert high_eval.is_blocking_alert
    assert high_eval.estimated_cost_multiplier_penalty == 10.0
    assert high_eval.recommended_action == "fork_branch"
    assert "Switching model from 'claude-3-7-sonnet' to 'gpt-4o'" in high_eval.warning_message

    # 4. Long session thinking level change -> MEDIUM risk, 5.0x cost penalty
    thinking_eval = evaluate_parameter_mutation(
        param_kind=CacheParameterKind.THINKING_LEVEL,
        old_value="high",
        new_value="low",
        current_tokens=18000,
        cache_alert_threshold=8000,
    )
    assert thinking_eval.risk_level == CacheRiskLevel.MEDIUM
    assert thinking_eval.is_blocking_alert
    assert thinking_eval.estimated_cost_multiplier_penalty == 5.0
    assert thinking_eval.recommended_action == "fork_branch"


def test_cache_preserving_branch_forking() -> None:
    """Verify smart branching forks a clean session while keeping the parent cache intact."""
    engine = CacheBreakPreventionShieldEngine(cache_alert_threshold=8000)
    session_id = "sess-cache-01"
    source_branch = "br-main"

    # Intercept mid-session mutation
    eval_result = engine.intercept_parameter_change(
        session_id=session_id,
        param_kind=CacheParameterKind.MODEL,
        old_value="claude-3-7-sonnet",
        new_value="claude-3-5-haiku",
        current_tokens=32000,
    )
    assert eval_result.is_blocking_alert
    assert eval_result.risk_level == CacheRiskLevel.CRITICAL

    # Fork new branch with transition summary
    fork_result = engine.fork_branch_with_cache_preservation(
        session_id=session_id,
        source_branch_id=source_branch,
        fork_anchor_turn=12,
        current_cached_tokens=32000,
        antecedent_summary="Summarized earlier architecture decisions for fast exploration.",
    )

    assert fork_result.source_branch_id == source_branch
    assert fork_result.new_branch_id.startswith("br-fork-")
    assert fork_result.fork_anchor_turn == 12
    assert fork_result.preserved_cache_tokens == 32000
    assert "Summarized earlier architecture decisions" in fork_result.transition_summary


def test_zero_cache_break_tail_rewind() -> None:
    """Verify tail-only rewind drops recent turns while preserving exact historical prefix cache."""
    engine = CacheBreakPreventionShieldEngine()
    session_id = "sess-rewind-02"

    history = [
        {"role": "user", "content": "Turn 1: Setup project"},
        {"role": "assistant", "content": "Turn 1: Project initialized"},
        {"role": "user", "content": "Turn 2: Add database schema"},
        {"role": "assistant", "content": "Turn 2: Database schema created"},
        {"role": "user", "content": "Turn 3: Bad request that strayed off course"},
        {"role": "assistant", "content": "Turn 3: Flawed execution response"},
    ]

    # Rewind the last 2 turns that went off track
    rewind_result, retained_messages = engine.rewind_tail_turns(
        session_id=session_id,
        messages=history,
        turns_to_drop=2,
        estimated_token_per_turn=600,
    )

    assert rewind_result.session_id == session_id
    assert rewind_result.dropped_turns_count == 2
    assert rewind_result.retained_turns_count == 4
    # The prefix remains 100% byte-for-byte identical, guaranteeing full upstream cache hit!
    assert rewind_result.cache_prefix_intact
    assert rewind_result.retained_cache_tokens_estimate == 2400

    assert len(retained_messages) == 4
    assert retained_messages[0]["content"] == "Turn 1: Setup project"
    assert retained_messages[3]["content"] == "Turn 2: Database schema created"
    # Flawed turns are eliminated from tail
    assert not any("Turn 3" in m["content"] for m in retained_messages)
