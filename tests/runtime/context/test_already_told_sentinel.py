from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context import (
    AlreadyToldIntentSentinel,
    HistoricalTurnInput,
    RecallStatus,
)


@pytest.fixture
def sentinel() -> AlreadyToldIntentSentinel:
    return AlreadyToldIntentSentinel(confidence_threshold=0.5)


def test_chinese_already_told_intent_recalled_with_strict_injection(
    sentinel: AlreadyToldIntentSentinel,
) -> None:
    history = [
        HistoricalTurnInput(turn_index=0, role="user", content="我想开发一个数据清洗脚本"),
        HistoricalTurnInput(turn_index=1, role="assistant", content="没问题，我们使用第三方库来解析。"),
        HistoricalTurnInput(turn_index=2, role="user", content="切记千万不要用 lodash 库，只能用原生 ES6 实现！"),
        HistoricalTurnInput(turn_index=3, role="assistant", content="好的，我使用 lodash.map 处理。"),
    ]

    query = "我刚才不是说了不要用 lodash 吗？！"
    res = sentinel.inspect_and_recall(query, history)

    assert res.detected is True
    assert res.status == RecallStatus.RECALLED_AND_ENFORCED
    assert res.matched_turn_index == 2
    assert "千万不要用 lodash 库" in (res.matched_instruction or "")
    assert res.confidence_score >= 0.6
    assert res.system_injection_block is not None
    assert "<system_verified_historical_user_instruction turn=\"2\"" in res.system_injection_block
    assert "[SYSTEM VERIFIED HISTORICAL USER INSTRUCTION]" in res.system_injection_block

    card = res.provenance_card
    assert card.detected is True
    assert card.matched_turn_index == 2
    assert card.status == RecallStatus.RECALLED_AND_ENFORCED.value


def test_english_already_told_intent_recalled(sentinel: AlreadyToldIntentSentinel) -> None:
    history = [
        HistoricalTurnInput(turn_index=0, role="user", content="Setup the theme styling"),
        HistoricalTurnInput(turn_index=1, role="assistant", content="Default theme configured."),
        HistoricalTurnInput(turn_index=2, role="user", content="The interface must use dark mode only"),
        HistoricalTurnInput(turn_index=3, role="assistant", content="Applied light theme."),
    ]

    query = "As I already told you earlier, use dark mode for the page"
    res = sentinel.inspect_and_recall(query, history)

    assert res.detected is True
    assert res.status == RecallStatus.RECALLED_AND_ENFORCED
    assert res.matched_turn_index == 2
    assert "dark mode" in (res.matched_instruction or "")
    assert res.confidence_score >= 0.5


def test_neutral_query_without_retrospective_intent(sentinel: AlreadyToldIntentSentinel) -> None:
    history = [
        HistoricalTurnInput(turn_index=0, role="user", content="帮我写一个快速排序算法"),
    ]
    query = "请帮我将它改写为二分查找"
    res = sentinel.inspect_and_recall(query, history)

    assert res.detected is False
    assert res.status == RecallStatus.NOT_DETECTED
    assert res.system_injection_block is None
    assert res.provenance_card.detected is False


def test_broad_retrospective_intent_fallback_to_constraint(sentinel: AlreadyToldIntentSentinel) -> None:
    history = [
        HistoricalTurnInput(turn_index=0, role="user", content="我们来搭建后端服务"),
        HistoricalTurnInput(turn_index=1, role="assistant", content="准备使用 MySQL 还是 SQLite？"),
        HistoricalTurnInput(turn_index=2, role="user", content="底层数据库必须使用 PostgreSQL"),
    ]
    query = "按原先说的办吧"
    res = sentinel.inspect_and_recall(query, history)

    assert res.detected is True
    assert res.status == RecallStatus.RECALLED_AND_ENFORCED
    assert res.matched_turn_index == 2
    assert "PostgreSQL" in (res.matched_instruction or "")


def test_retrospective_intent_empty_history_fallback_warning(sentinel: AlreadyToldIntentSentinel) -> None:
    history: list[HistoricalTurnInput] = []
    query = "我之前不是交代过了吗！"
    res = sentinel.inspect_and_recall(query, history)

    assert res.detected is True
    assert res.status == RecallStatus.FALLBACK_WARN
    assert res.matched_turn_index is None
    assert res.system_injection_block is None
    assert res.provenance_card.status == RecallStatus.FALLBACK_WARN.value


def test_assistant_turns_are_never_recalled_as_user_instructions(
    sentinel: AlreadyToldIntentSentinel,
) -> None:
    history = [
        HistoricalTurnInput(turn_index=0, role="user", content="我想写一个爬虫"),
        # Assistant mentioned lodash, but user never said it
        HistoricalTurnInput(turn_index=1, role="assistant", content="建议切勿使用 lodash"),
    ]
    query = "我刚才不是说过了不要用 lodash 吗？"
    res = sentinel.inspect_and_recall(query, history)

    # Since user never said lodash in user turns, it shouldn't falsely attribute to turn 1 assistant
    assert res.matched_turn_index != 1
