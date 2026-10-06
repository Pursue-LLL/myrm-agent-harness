# [POS] tests/toolkits/memory/test_auto_recall_gate.py
# [INPUT] myrm_agent_harness.toolkits.memory.auto_recall
# [OUTPUT] Unit tests verifying trigger classification, 5-turn sliding dedup, and fail-open reranking

"""Unit tests for Targeted Experience Auto-Recall Engine."""

from __future__ import annotations

import time

from myrm_agent_harness.toolkits.memory.auto_recall import (
    AutoRecallDecision,
    ExperienceRecallGate,
    ExperienceRecallTriggerClassifier,
    FailOpenReranker,
    RecallCandidate,
    RecallGateConfig,
    RecallTriggerType,
    RerankerStatus,
    SlidingWindowDedupGate,
)


def test_trigger_classifier_explicit_events() -> None:
    """Verify that explicit lifecycle events trigger correct high-risk scenarios."""
    scenarios = [
        ("task_start", RecallTriggerType.TASK_START),
        ("skill_load", RecallTriggerType.SKILL_LOAD),
        ("subagent_start", RecallTriggerType.SUBAGENT_START),
        ("write_preflight", RecallTriggerType.WRITE_PREFLIGHT),
        ("cron_start", RecallTriggerType.CRON_START),
    ]
    for ev, expected_type in scenarios:
        res_type, reason = ExperienceRecallTriggerClassifier.classify(event_name=ev)
        assert res_type == expected_type
        assert "Explicit event" in reason


def test_trigger_classifier_tools_and_text() -> None:
    """Verify tool names and textual heuristics detect triggers, casual chat is suppressed."""
    # Tool match
    t1, _ = ExperienceRecallTriggerClassifier.classify(tool_name="write_to_file")
    assert t1 == RecallTriggerType.WRITE_PREFLIGHT

    t2, _ = ExperienceRecallTriggerClassifier.classify(tool_name="invoke_subagent")
    assert t2 == RecallTriggerType.SUBAGENT_START

    # Text pattern match
    t3, _ = ExperienceRecallTriggerClassifier.classify(query_text="Please delete the old config")
    assert t3 == RecallTriggerType.WRITE_PREFLIGHT

    t4, _ = ExperienceRecallTriggerClassifier.classify(query_text="Plan the new task execution")
    assert t4 == RecallTriggerType.TASK_START

    # Non-sensitive casual chat
    t_none, reason_none = ExperienceRecallTriggerClassifier.classify(
        query_text="What is the weather today?"
    )
    assert t_none == RecallTriggerType.NONE
    assert "auto-recall suppressed" in reason_none


def test_sliding_window_dedup_gate() -> None:
    """Verify 5-turn sliding window suppresses repeat memory injections and slides correctly."""
    gate = SlidingWindowDedupGate(window_turns=3)
    cand1 = RecallCandidate(memory_id="mem_1", content="Rule 1", initial_score=0.9)
    cand2 = RecallCandidate(memory_id="mem_2", content="Rule 2", initial_score=0.8)

    session_id = "test_sess_001"

    # Turn 1: None injected yet, all survive filter
    unseen = gate.filter_unseen(session_id, [cand1, cand2])
    assert len(unseen) == 2

    # Injected mem_1 at Turn 1
    gate.record_injected(session_id, ["mem_1"], turn_index=1)
    stats1 = gate.get_session_stats(session_id)
    assert stats1["active_window_turns"] == 1
    assert stats1["total_suppressed_id_count"] == 1

    # Turn 2: cand1 suppressed, cand2 remains
    unseen_turn2 = gate.filter_unseen(session_id, [cand1, cand2])
    assert len(unseen_turn2) == 1
    assert unseen_turn2[0].memory_id == "mem_2"

    # Injected mem_2 at Turn 2, and dummy mem_3 at Turn 3
    gate.record_injected(session_id, ["mem_2"], turn_index=2)
    gate.record_injected(session_id, ["mem_3"], turn_index=3)

    # Injected mem_4 at Turn 4 (Window is size 3: covers turns 2, 3, 4 -> Turn 1 mem_1 slides out!)
    gate.record_injected(session_id, ["mem_4"], turn_index=4)

    # Now mem_1 is no longer in window [mem_2, mem_3, mem_4]
    unseen_turn5 = gate.filter_unseen(session_id, [cand1])
    assert len(unseen_turn5) == 1
    assert unseen_turn5[0].memory_id == "mem_1"

    # Clear session
    gate.clear_session(session_id)
    assert gate.get_session_stats(session_id)["active_window_turns"] == 0


def test_fail_open_reranker_behaviors() -> None:
    """Verify fail-open reranker skips when no key, times out, or catches exceptions."""
    cand1 = RecallCandidate(memory_id="m1", content="Database migration", initial_score=0.6)
    cand2 = RecallCandidate(memory_id="m2", content="FastAPI router", initial_score=0.9)

    # 1. No key -> skipped status with score descending order
    reranker = FailOpenReranker(config=RecallGateConfig(api_key_env_var="NON_EXISTENT_KEY"))
    res, status = reranker.rerank(query="Database", candidates=[cand1, cand2])
    assert status == RerankerStatus.RERANKER_SKIPPED
    assert [c.memory_id for c in res] == ["m2", "m1"]

    # 2. Custom rerank function success
    def _mock_rerank(q: str, cands: list[RecallCandidate]) -> list[RecallCandidate]:
        return list(reversed(cands))

    reranker_custom = FailOpenReranker(custom_rerank_fn=_mock_rerank)
    res_custom, status_custom = reranker_custom.rerank(query="test", candidates=[cand1, cand2])
    assert status_custom == RerankerStatus.APPLIED
    assert [c.memory_id for c in res_custom] == ["m2", "m1"]

    # 3. Timeout simulation -> fail-open fallback
    def _slow_rerank(q: str, cands: list[RecallCandidate]) -> list[RecallCandidate]:
        time.sleep(0.05)
        return []

    reranker_timeout = FailOpenReranker(
        config=RecallGateConfig(reranker_timeout_ms=10.0),
        custom_rerank_fn=_slow_rerank,
    )
    res_to, status_to = reranker_timeout.rerank(query="test", candidates=[cand1, cand2])
    assert status_to == RerankerStatus.TIMED_OUT
    assert len(res_to) == 2

    # 4. Error simulation -> fail-open fallback
    def _broken_rerank(q: str, cands: list[RecallCandidate]) -> list[RecallCandidate]:
        msg = "Downstream connection reset"
        raise RuntimeError(msg)

    reranker_broken = FailOpenReranker(custom_rerank_fn=_broken_rerank)
    res_err, status_err = reranker_broken.rerank(query="test", candidates=[cand1, cand2])
    assert status_err == RerankerStatus.FAILED_OPEN
    assert len(res_err) == 2


def test_experience_recall_gate_lifecycle() -> None:
    """Verify end-to-end orchestration of trigger filtering, sliding dedup, and recall decision."""
    gate = ExperienceRecallGate(
        config=RecallGateConfig(min_recall_score=0.5, max_injected_items=2, dedup_turns=2)
    )

    cands = [
        RecallCandidate(memory_id="m1", content="Fix for SQL race condition", initial_score=0.9),
        RecallCandidate(memory_id="m2", content="Git branch push rule", initial_score=0.7),
        RecallCandidate(memory_id="m3", content="Low score noise", initial_score=0.3),
    ]

    session_id = "session_orch_999"

    # Turn 1: Casual question -> Auto-recall suppressed completely
    dec1: AutoRecallDecision = gate.evaluate_and_recall(
        session_id=session_id,
        current_turn=1,
        raw_candidates=cands,
        query_text="What is your name?",
    )
    assert not dec1.triggered
    assert dec1.trigger_type == RecallTriggerType.NONE
    assert len(dec1.injected_candidates) == 0

    # Turn 2: High-risk write preflight trigger
    dec2: AutoRecallDecision = gate.evaluate_and_recall(
        session_id=session_id,
        current_turn=2,
        raw_candidates=cands,
        event_name="write_preflight",
        tool_name="write_to_file",
    )
    assert dec2.triggered
    assert dec2.trigger_type == RecallTriggerType.WRITE_PREFLIGHT
    assert dec2.candidates_pre_dedup == 3
    # m3 (<0.5) was filtered out, m1 and m2 survived dedup
    assert dec2.candidates_post_dedup == 2
    assert len(dec2.injected_candidates) == 2
    assert [c.memory_id for c in dec2.injected_candidates] == ["m1", "m2"]

    # Turn 3: Same session, immediate next write preflight -> both m1 and m2 suppressed by dedup!
    dec3: AutoRecallDecision = gate.evaluate_and_recall(
        session_id=session_id,
        current_turn=3,
        raw_candidates=cands,
        tool_name="replace_file_content",
    )
    assert dec3.triggered
    assert dec3.candidates_post_dedup == 0
    assert len(dec3.injected_candidates) == 0
    assert "suppressed by 5-turn dedup window" in dec3.audit_reason
