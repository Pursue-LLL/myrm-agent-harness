"""Unit tests for DeterministicIntentRouter and QueryIntent categories.

Validates zero-LLM-cost pattern matching, confidence scoring,
channel targeting, sub-graph selection, and ReDoS safety.
"""


from myrm_agent_harness.toolkits.memory.intent_recognizers import (
    DeterministicIntentRouter,
    KeywordBasedRecognizer,
    QueryIntent,
)
from myrm_agent_harness.toolkits.memory.types import MemoryType


def test_action_guidance_intent_recognition() -> None:
    router = DeterministicIntentRouter()
    query = "打包又报错了，提示 cannot find module core_ip_manifest，该怎么解决？"
    decision = router.recognize(query)

    assert decision.intent == QueryIntent.ACTION_GUIDANCE
    assert decision.confidence >= DeterministicIntentRouter.HIGH_CONFIDENCE_THRESHOLD
    assert decision.routing_mode == "pruned"
    assert MemoryType.PROCEDURAL in decision.target_types
    assert "procedural" in decision.target_subgraphs
    assert decision.type_weights[MemoryType.PROCEDURAL] > decision.type_weights[MemoryType.CONVERSATION]


def test_episodic_causal_intent_recognition() -> None:
    router = DeterministicIntentRouter()
    query = "我们上次为什么决定将存储层重构成单机 SQLite 架构？"
    decision = router.recognize(query)

    assert decision.intent == QueryIntent.EPISODIC_CAUSAL
    assert decision.confidence >= DeterministicIntentRouter.HIGH_CONFIDENCE_THRESHOLD
    assert decision.routing_mode == "pruned"
    assert MemoryType.EPISODIC in decision.target_types
    assert "causal" in decision.target_subgraphs


def test_user_profile_intent_recognition() -> None:
    router = DeterministicIntentRouter()
    query = "我的习惯是在函数参数中强制使用具体类型而不是 Any"
    decision = router.recognize(query)

    assert decision.intent == QueryIntent.USER_PROFILE
    assert decision.confidence >= DeterministicIntentRouter.HIGH_CONFIDENCE_THRESHOLD
    assert MemoryType.PROFILE in decision.target_types
    assert decision.type_weights[MemoryType.PROFILE] >= 1.5


def test_knowledge_fact_intent_recognition() -> None:
    router = DeterministicIntentRouter()
    query = "解释一下什么是 RRF 融合算法以及它的公式定义"
    decision = router.recognize(query)

    assert decision.intent == QueryIntent.KNOWLEDGE_FACT
    assert decision.confidence >= DeterministicIntentRouter.HIGH_CONFIDENCE_THRESHOLD
    assert MemoryType.SEMANTIC in decision.target_types
    assert "knowledge" in decision.target_subgraphs


def test_general_fallback_intent() -> None:
    router = DeterministicIntentRouter()
    query = "今天天气不错，你好呀"
    decision = router.recognize(query)

    assert decision.intent == QueryIntent.GENERAL
    assert decision.confidence <= DeterministicIntentRouter.MODERATE_CONFIDENCE_THRESHOLD
    assert decision.routing_mode == "broadcast"
    # Fallback activates all standard types
    assert len(decision.target_types) == 5


def test_empty_query_safety() -> None:
    router = DeterministicIntentRouter()
    decision = router.recognize("")
    assert decision.intent == QueryIntent.GENERAL
    assert decision.confidence == 0.0


def test_long_stack_trace_truncation_safety() -> None:
    router = DeterministicIntentRouter()
    # 5000 characters of stack trace
    long_query = "Build failed with exit code 1:\n" + ("at file.ts:123:45\n" * 300)
    decision = router.recognize(long_query)

    # Should safely recognize ACTION_GUIDANCE without timing out
    assert decision.intent == QueryIntent.ACTION_GUIDANCE
    assert decision.confidence >= 0.85


def test_backward_compatibility_alias() -> None:
    recognizer = KeywordBasedRecognizer()
    decision = recognizer.recognize("报错怎么修复")
    assert decision.intent == QueryIntent.ACTION_GUIDANCE
