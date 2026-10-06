# [POS] tests/toolkits/memory/test_memory_crystallization.py
# [INPUT] types, governor
# [OUTPUT] test_formation_gate_importance_filtering, test_application_facet_routing_and_priority, test_reflection_same_session_secondary_error_penalty_and_retirement, test_recovery_and_degraded_state_transitions

from myrm_agent_harness.toolkits.memory.crystallization import (
    ProceduralCrystallizationGovernor,
    RuleLifecycleState,
)


def test_formation_gate_importance_filtering() -> None:
    """Verify formation-stage two-factor gate passes high impact rules and discards trivial noise."""
    governor = ProceduralCrystallizationGovernor(importance_threshold=0.70)

    # 1. High-signal production rule: confidence=0.90, severity=0.85 -> 0.7650
    high_signal = governor.evaluate_formation_gate(
        confidence=0.90,
        severity=0.85,
        content="Docker 容器通信必须使用自定义 bridge 网络，避免使用 host 模式",
    )
    assert high_signal.passed_gate is True
    assert high_signal.importance == 0.765
    assert "approved for crystallization" in high_signal.gate_reason.lower()

    # 2. Ephemeral trivial dialogue: confidence=0.50, severity=0.40 -> 0.2000
    low_signal = governor.evaluate_formation_gate(
        confidence=0.50,
        severity=0.40,
        content="今天天气不错，稍后帮我查一下外卖",
    )
    assert low_signal.passed_gate is False
    assert low_signal.importance == 0.2000
    assert "filtered out" in low_signal.gate_reason.lower()


def test_application_facet_routing_and_priority() -> None:
    """Verify application-stage facet-scoped routing isolates domain rules and respects priority."""
    governor = ProceduralCrystallizationGovernor()

    r_devops = governor.register_rule("rule_devops", facets=["devops"], description="DevOps bridge config")
    r_frontend = governor.register_rule("rule_fe", facets=["frontend"], description="React memo rule")
    r_global = governor.register_rule("rule_global", facets=["global"], description="Safe execution confirmation")

    all_rules = [r_devops, r_frontend, r_global]

    # Scoped to devops only
    matched_devops = governor.filter_by_facets(all_rules, active_facets=["devops"])
    matched_ids = [r.rule_id for r in matched_devops]
    assert "rule_devops" in matched_ids
    assert "rule_global" in matched_ids
    assert "rule_fe" not in matched_ids

    # Global scope includes all non-retired rules
    matched_all = governor.filter_by_facets(all_rules, active_facets=["global"])
    assert len(matched_all) == 3


def test_reflection_same_session_secondary_error_penalty_and_retirement() -> None:
    """Verify reflection-stage penalty for repeat same-session failures and dynamic retirement."""
    governor = ProceduralCrystallizationGovernor(
        min_trials_for_transition=3,
        retire_threshold=0.20,
    )

    rule_id = "flaky_rule_01"
    session_id = "session_debug_101"

    # Turn 1: failure in session
    m1 = governor.record_execution_feedback(
        rule_id=rule_id,
        session_id=session_id,
        is_success=False,
    )
    assert m1.fail_count == 1
    assert m1.state == RuleLifecycleState.ACTIVE

    # Turn 2: repeat failure in the same session triggers heavier penalty
    m2 = governor.record_execution_feedback(
        rule_id=rule_id,
        session_id=session_id,
        is_success=False,
    )
    assert m2.fail_count == 3  # Incremented by 2 for repeat same-session failure

    # Turn 3: third failure drops win rate to 0.0, retiring the rule
    m3 = governor.record_execution_feedback(
        rule_id=rule_id,
        session_id=session_id,
        is_success=False,
    )
    assert m3.win_rate == 0.0
    assert m3.state == RuleLifecycleState.RETIRED
    assert m3.weight == 0.0

    # Ensure retired rule is excluded during facet filtering
    active_candidates = governor.filter_by_facets([m3], active_facets=["global"])
    assert len(active_candidates) == 0


def test_recovery_and_degraded_state_transitions() -> None:
    """Verify lifecycle degradation and subsequent recovery upon consistent successes."""
    governor = ProceduralCrystallizationGovernor(
        min_trials_for_transition=3,
        degrade_threshold=0.40,
        recover_threshold=0.60,
    )

    rule_id = "recovering_rule_02"

    # Seed with 1 success and 2 failures -> win rate = 1/3 = 0.3333 (DEGRADED)
    governor.record_execution_feedback(rule_id=rule_id, session_id="s1", is_success=True)
    governor.record_execution_feedback(rule_id=rule_id, session_id="s2", is_success=False)
    m = governor.record_execution_feedback(rule_id=rule_id, session_id="s3", is_success=False)

    assert m.state == RuleLifecycleState.DEGRADED
    assert m.win_rate < 0.40

    # Human intervention / successful runs: 4 consecutive successes
    governor.record_execution_feedback(rule_id=rule_id, session_id="s4", is_success=True)
    governor.record_execution_feedback(rule_id=rule_id, session_id="s5", is_success=True)
    governor.record_execution_feedback(rule_id=rule_id, session_id="s6", is_success=True)
    recovered = governor.record_execution_feedback(rule_id=rule_id, session_id="s7", is_success=True)

    # 5 successes, 2 failures -> win rate = 5/7 = 0.7143 >= 0.60 -> ACTIVE
    assert recovered.state == RuleLifecycleState.ACTIVE
    assert recovered.win_rate >= 0.60
    assert recovered.weight > 0.50
