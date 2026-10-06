# [POS] tests/toolkits/memory/test_memory_intent_reflection.py
# [INPUT] types, classifier, probe, ProceduralMemory
# [OUTPUT] test_tier_0_fast_path_bypass_and_zero_rules, test_tier_1_code_execution_facet_activation, test_tier_2_knowledge_content_suppresses_code_rules, test_pluggable_reflection_probe_delegation_and_fault_tolerance

from myrm_agent_harness.toolkits.memory.intent_reflection import (
    IntentClassificationResult,
    IntentLevelClassifier,
    IntentTier,
    PlaybookActivationProbe,
    ReflectionProbeProtocol,
)
from myrm_agent_harness.toolkits.memory.types import ProceduralMemory


def _create_rule(
    rule_id: str,
    facets: list[str],
    action: str = "execute",
    trigger: str = "when requested",
    is_active: bool = True,
    lifecycle_state: str = "active",
) -> ProceduralMemory:
    """Helper to instantiate a ProceduralMemory with facets and lifecycle state."""
    return ProceduralMemory(
        id=rule_id,
        user_id="u_test",
        trigger=trigger,
        action=action,
        facets=facets,
        is_active=is_active,
        lifecycle_state=lifecycle_state,
    )


def test_tier_0_fast_path_bypass_and_zero_rules() -> None:
    """Verify flow controls, short affirmations, and empty queries bypass retrieval with 0 injected rules."""
    probe = PlaybookActivationProbe()
    candidates = [
        _create_rule("r_devops", facets=["devops"]),
        _create_rule("r_global", facets=["global"]),
        _create_rule("r_writing", facets=["writing"]),
    ]

    for flow_input in ["好的", "继续", "ok", "got it", "help", "status", "   "]:
        decision = probe.evaluate(query=flow_input, candidates=candidates)
        assert decision.tier == IntentTier.TIER_0_FAST_PATH
        assert decision.bypass_retrieval is True
        assert len(decision.activated_rules) == 0
        assert decision.suppressed_rules_count == len(candidates)
        assert "fast path" in decision.decision_reason.lower()


def test_tier_1_code_execution_facet_activation() -> None:
    """Verify CLI, docker commands, and code snippets activate coding facets and suppress writing rules."""
    probe = PlaybookActivationProbe()
    candidates = [
        _create_rule("r_devops", facets=["devops"]),
        _create_rule("r_coding", facets=["coding"]),
        _create_rule("r_global", facets=["global"]),
        _create_rule("r_writing", facets=["writing"]),
        _create_rule("r_biz", facets=["business"]),
    ]

    code_query = "帮我执行 docker compose up -d 并调试 python 报错"
    decision = probe.evaluate(query=code_query, candidates=candidates)

    assert decision.tier == IntentTier.TIER_1_CODE_EXECUTION
    assert decision.bypass_retrieval is False
    assert "coding" in decision.active_facets
    assert "devops" in decision.active_facets

    activated_ids = [r.id for r in decision.activated_rules]
    assert "r_devops" in activated_ids
    assert "r_coding" in activated_ids
    assert "r_global" in activated_ids
    assert "r_writing" not in activated_ids
    assert "r_biz" not in activated_ids
    assert decision.suppressed_rules_count == 2


def test_tier_2_knowledge_content_suppresses_code_rules() -> None:
    """Verify research and document drafting activates content facets and suppresses devops rules."""
    probe = PlaybookActivationProbe()
    candidates = [
        _create_rule("r_devops", facets=["devops"]),
        _create_rule("r_coding", facets=["coding"]),
        _create_rule("r_global", facets=["global"]),
        _create_rule("r_writing", facets=["writing"]),
        _create_rule("r_retired", facets=["writing"], lifecycle_state="retired"),
    ]

    doc_query = "请帮我撰写一份关于竞品架构演进的分析总结报告"
    decision = probe.evaluate(query=doc_query, candidates=candidates)

    assert decision.tier == IntentTier.TIER_2_KNOWLEDGE_CONTENT
    assert decision.bypass_retrieval is False
    assert "writing" in decision.active_facets

    activated_ids = [r.id for r in decision.activated_rules]
    assert "r_writing" in activated_ids
    assert "r_global" in activated_ids
    assert "r_devops" not in activated_ids
    assert "r_coding" not in activated_ids
    assert "r_retired" not in activated_ids
    assert decision.suppressed_rules_count == 3


def test_pluggable_reflection_probe_delegation_and_fault_tolerance() -> None:
    """Verify sidecar reflection probe delegation and graceful fallback when probe errors."""

    class MockCustomProbe(ReflectionProbeProtocol):
        def __init__(self, should_fail: bool = False) -> None:
            self.should_fail = should_fail

        def classify(
            self,
            query: str,
            context: dict[str, str] | None = None,
        ) -> IntentClassificationResult | None:
            if self.should_fail:
                raise RuntimeError("Sidecar probe network connection timed out")
            return IntentClassificationResult(
                tier=IntentTier.TIER_3_DEEP_REASONING,
                confidence=0.99,
                matched_keywords=("mock_neural_signal",),
                suggested_facets=("global",),
                source="reflection_probe",
                reason="Neural reflection probe determined deep reasoning required.",
            )

    # 1. Custom probe succeeds
    custom_classifier = IntentLevelClassifier(probe=MockCustomProbe(should_fail=False))
    probe = PlaybookActivationProbe(classifier=custom_classifier)
    candidates = [_create_rule("r1", facets=["custom"])]
    decision = probe.evaluate("这是一条常规业务咨询", candidates=candidates)

    assert decision.tier == IntentTier.TIER_3_DEEP_REASONING
    assert len(decision.activated_rules) == 1

    # 2. Custom probe fails -> fallback to heuristic
    faulty_classifier = IntentLevelClassifier(probe=MockCustomProbe(should_fail=True))
    probe_faulty = PlaybookActivationProbe(classifier=faulty_classifier)
    decision_fallback = probe_faulty.evaluate("好的", candidates=candidates)
    assert decision_fallback.tier == IntentTier.TIER_0_FAST_PATH
    assert decision_fallback.bypass_retrieval is True
