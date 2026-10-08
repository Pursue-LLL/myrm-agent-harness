"""Unit tests for NaturalLanguageMemoryFeedbackAndLiveCorrectionSuite in harness.

[INPUT]
- myrm_agent_harness.toolkits.memory.live_correction

[OUTPUT]
- Pytest test cases verifying detection, localization, atomic mutation, and orchestration.

[POS]
tests/toolkits/memory/test_natural_language_live_correction_suite.py
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.memory import (
    AtomicMemoryMutator,
    CorrectionAckReceipt,
    CorrectionIntentKind,
    CorrectionTargetLocalizer,
    LiveCorrectionOrchestrator,
    MutationAction,
    NaturalLanguageCorrectionDetector,
    TargetNodeCandidate,
)


@pytest.fixture
def detector() -> NaturalLanguageCorrectionDetector:
    return NaturalLanguageCorrectionDetector()


@pytest.fixture
def localizer() -> CorrectionTargetLocalizer:
    return CorrectionTargetLocalizer(match_threshold=0.3)


@pytest.fixture
def mutator() -> AtomicMemoryMutator:
    return AtomicMemoryMutator()


@pytest.fixture
def orchestrator() -> LiveCorrectionOrchestrator:
    return LiveCorrectionOrchestrator()


def test_detector_chinese_preference_update(detector: NaturalLanguageCorrectionDetector) -> None:
    utterance = "我更喜欢无糖乌龙茶而不是拿铁"
    slot = detector.detect(utterance)
    assert slot is not None
    assert slot.intent == CorrectionIntentKind.PREFERENCE_UPDATE
    assert slot.corrected_value == "无糖乌龙茶"
    assert slot.negated_value == "拿铁"


def test_detector_english_preference_update(detector: NaturalLanguageCorrectionDetector) -> None:
    utterance = "I prefer Rust instead of Go"
    slot = detector.detect(utterance)
    assert slot is not None
    assert slot.intent == CorrectionIntentKind.PREFERENCE_UPDATE
    assert slot.corrected_value == "Rust"
    assert slot.negated_value == "Go"


def test_detector_chinese_fact_superseded(detector: NaturalLanguageCorrectionDetector) -> None:
    utterance = "你记错了，主数据库不是 Postgres，实际上是 SQLite"
    slot = detector.detect(utterance)
    assert slot is not None
    assert slot.intent == CorrectionIntentKind.FACT_SUPERSEDED
    assert slot.negated_value == "Postgres"
    assert slot.corrected_value == "SQLite"


def test_detector_behavior_rule_and_retract(detector: NaturalLanguageCorrectionDetector) -> None:
    rule_utterance = "以后不要直接执行脚本，必须走审批流"
    slot_rule = detector.detect(rule_utterance)
    assert slot_rule is not None
    assert slot_rule.intent == CorrectionIntentKind.BEHAVIOR_RULE

    retract_utterance = "撤回关于临时测试密钥的记忆"
    slot_retract = detector.detect(retract_utterance)
    assert slot_retract is not None
    assert slot_retract.intent == CorrectionIntentKind.RETRACT_MISTAKE


def test_detector_non_correction_returns_none(detector: NaturalLanguageCorrectionDetector) -> None:
    assert detector.detect("今天天气真不错") is None
    assert detector.detect("请帮我写一个快速排序算法") is None
    assert detector.detect("") is None


def test_localizer_identifies_matching_node(
    detector: NaturalLanguageCorrectionDetector,
    localizer: CorrectionTargetLocalizer,
) -> None:
    slot = detector.detect("我不喜欢拿铁，更喜欢无糖乌龙茶")
    assert slot is not None

    candidates = [
        TargetNodeCandidate(memory_id="node_1", content="用户偏好饮品：美式咖啡"),
        TargetNodeCandidate(memory_id="node_2", content="用户常喝拿铁咖啡"),
        TargetNodeCandidate(memory_id="node_3", content="用户常用 IDE 为 VS Code"),
    ]

    target = localizer.localize(slot, candidates)
    assert target is not None
    assert target.memory_id == "node_2"
    assert target.match_score >= 0.9


def test_localizer_no_match_returns_none(
    detector: NaturalLanguageCorrectionDetector,
    localizer: CorrectionTargetLocalizer,
) -> None:
    slot = detector.detect("我不喜欢跳伞，更喜欢潜水")
    assert slot is not None

    candidates = [
        TargetNodeCandidate(memory_id="node_1", content="用户喜欢写 Python 代码"),
    ]

    assert localizer.localize(slot, candidates) is None


def test_mutator_supersede_and_retract(
    detector: NaturalLanguageCorrectionDetector,
    mutator: AtomicMemoryMutator,
) -> None:
    slot = detector.detect("我更喜欢深色模式而不是浅色模式")
    assert slot is not None

    target = TargetNodeCandidate(memory_id="node_theme", content="用户界面偏好浅色模式")
    result = mutator.mutate(slot, target)

    assert result.action == MutationAction.SUPERSEDE
    assert result.target_memory_id == "node_theme"
    assert result.new_content == "深色模式"
    assert result.status == "applied"
    assert len(mutator.history) == 1


def test_orchestrator_end_to_end_receipt(orchestrator: LiveCorrectionOrchestrator) -> None:
    candidates = [
        TargetNodeCandidate(memory_id="mem_drink_1", content="用户爱喝拿铁"),
    ]

    receipt = orchestrator.process_utterance("我更喜欢无糖乌龙茶而不是拿铁", candidates)
    assert receipt is not None
    assert isinstance(receipt, CorrectionAckReceipt)
    assert receipt.success is True
    assert "无糖乌龙茶" in receipt.ack_message
    assert receipt.mutated_record is not None
    assert receipt.mutated_record.action == MutationAction.SUPERSEDE

    # Negative check for normal conversation
    assert orchestrator.process_utterance("今天有什么新闻？", candidates) is None
