"""Unit tests for NaturalLanguageMemoryFeedbackAndLiveCorrectionSuite (Item 128 P0).

Validates in-conversation conversational correction detection, conflict localization,
atomic memory state mutation, and natural language acknowledgement synthesis.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.live_correction import (
    AtomicMemoryMutator,
    CorrectionAckReceipt,
    CorrectionIntentKind,
    CorrectionSlot,
    CorrectionTargetLocalizer,
    LiveCorrectionMutationResult,
    LiveCorrectionOrchestrator,
    MutationAction,
    NaturalLanguageCorrectionDetector,
    TargetNodeCandidate,
)


def test_detector_chinese_preference_and_fact_superseded() -> None:
    """Test Chinese correction patterns for preference update and fact supersession."""
    detector = NaturalLanguageCorrectionDetector()

    # Pattern: 我更喜欢 Y 而不是 X
    slot_pref = detector.detect("我更喜欢 Rust 而不是 C++")
    assert slot_pref is not None
    assert slot_pref.intent == CorrectionIntentKind.PREFERENCE_UPDATE
    assert slot_pref.corrected_value == "Rust"
    assert slot_pref.negated_value == "C++"

    # Pattern: 不对，主数据库不是 Postgres，而是 SQLite
    slot_fact = detector.detect("不对，主数据库不是 Postgres，而是 SQLite")
    assert slot_fact is not None
    assert slot_fact.intent == CorrectionIntentKind.FACT_SUPERSEDED
    assert slot_fact.corrected_value == "SQLite"
    assert slot_fact.negated_value == "Postgres"


def test_detector_english_and_retraction() -> None:
    """Test English patterns and retraction commands."""
    detector = NaturalLanguageCorrectionDetector()

    slot_en = detector.detect("I prefer dark mode instead of light mode")
    assert slot_en is not None
    assert slot_en.intent == CorrectionIntentKind.PREFERENCE_UPDATE
    assert slot_en.corrected_value == "dark mode"
    assert slot_en.negated_value == "light mode"

    slot_retract = detector.detect("撤回之前关于 旧密码 的记忆")
    assert slot_retract is not None
    assert slot_retract.intent == CorrectionIntentKind.RETRACT_MISTAKE
    assert slot_retract.negated_value == "旧密码"


def test_localizer_matching_candidate() -> None:
    """Test semantic localization of target candidate memory nodes."""
    localizer = CorrectionTargetLocalizer(match_threshold=0.3)

    slot = CorrectionSlot(
        corrected_value="Rust",
        negated_value="C++",
        subject=None,
        intent=CorrectionIntentKind.PREFERENCE_UPDATE,
        raw_utterance="我更喜欢 Rust 而不是 C++",
    )

    candidates = [
        TargetNodeCandidate(
            memory_id="mem_1",
            content="用户平时习惯使用 Python 编写脚本",
            cube_id="cube_user",
        ),
        TargetNodeCandidate(
            memory_id="mem_2",
            content="用户偏好系统编程语言为 C++ 并使用 CMake",
            cube_id="cube_user",
        ),
    ]

    matched = localizer.localize(slot, candidates)
    assert matched is not None
    assert matched.memory_id == "mem_2"
    assert matched.match_score >= 0.90


def test_atomic_mutator_supersede_and_retract() -> None:
    """Test atomic memory state machine transitions."""
    mutator = AtomicMemoryMutator()

    # Case 1: Supersede
    slot_update = CorrectionSlot(
        corrected_value="SQLite WAL",
        negated_value="MySQL",
        intent=CorrectionIntentKind.FACT_SUPERSEDED,
        raw_utterance="不是 MySQL，而是 SQLite WAL",
    )
    target = TargetNodeCandidate(
        memory_id="mem_db_old",
        content="当前架构使用的持久化数据库为 MySQL",
        match_score=0.95,
    )

    res_supersede: LiveCorrectionMutationResult = mutator.mutate(slot_update, target)
    assert res_supersede.action == MutationAction.SUPERSEDE
    assert res_supersede.target_memory_id == "mem_db_old"
    assert res_supersede.new_memory_id is not None
    assert res_supersede.new_content == "SQLite WAL"
    assert res_supersede.superseded_content == "当前架构使用的持久化数据库为 MySQL"

    # Case 2: Retract
    slot_retract = CorrectionSlot(
        corrected_value="撤回: 测试密码",
        negated_value="测试密码",
        intent=CorrectionIntentKind.RETRACT_MISTAKE,
        raw_utterance="删除关于 测试密码 的记录",
    )
    target_pwd = TargetNodeCandidate(
        memory_id="mem_pwd_123",
        content="临时测试密码为 Admin@123",
        match_score=0.95,
    )
    res_retract = mutator.mutate(slot_retract, target_pwd)
    assert res_retract.action == MutationAction.RETRACT
    assert res_retract.status == "retracted"
    assert res_retract.new_memory_id is None
    assert len(mutator.history) == 2


def test_orchestrator_end_to_end_receipt_synthesis() -> None:
    """Test full pipeline orchestration from conversational utterance to ack receipt."""
    orchestrator = LiveCorrectionOrchestrator()

    candidates = [
        TargetNodeCandidate(
            memory_id="mem_coffee_1",
            content="用户每天早晨喜欢喝 美式咖啡",
            cube_id="pref_cube",
        )
    ]

    receipt: CorrectionAckReceipt | None = orchestrator.process_utterance(
        "我不喜欢美式咖啡，换成燕麦拿铁",
        candidates=candidates,
    )

    assert receipt is not None
    assert receipt.success is True
    assert receipt.intent == CorrectionIntentKind.PREFERENCE_UPDATE
    assert "更正偏好" in receipt.ack_message or "更新偏好" in receipt.ack_message
    assert "燕麦拿铁" in receipt.ack_message
    assert receipt.mutated_record is not None
    assert receipt.mutated_record.action == MutationAction.SUPERSEDE
    assert receipt.mutated_record.new_content == "燕麦拿铁"
