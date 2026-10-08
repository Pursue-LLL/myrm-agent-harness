"""Unit tests for targeted experience auto-recall agent tool and MemoryManager mixin."""

from __future__ import annotations

import json

from myrm_agent_harness.toolkits.memory._manager.auto_recall import (
    MemoryManagerAutoRecallMixin,
)
from myrm_agent_harness.toolkits.memory.auto_recall.recall_gate import (
    ExperienceRecallGate,
)
from myrm_agent_harness.toolkits.memory.auto_recall.tool import (
    create_auto_recall_evaluator_tool,
)
from myrm_agent_harness.toolkits.memory.auto_recall.types import (
    RecallCandidate,
    RecallGateConfig,
    RecallTriggerType,
    RerankerStatus,
)


class DummyAutoRecallMemoryManager(MemoryManagerAutoRecallMixin):
    """Dummy MemoryManager subclass for testing auto recall mixin."""

    def __init__(self) -> None:
        self.user_id = "test_user"


SAMPLE_CANDIDATES = [
    {
        "memory_id": "mem-01",
        "content": "Always check filesystem permissions before removing cache files.",
        "initial_score": 0.85,
    },
    {
        "memory_id": "mem-02",
        "content": "Verify port availability before launching internal test server.",
        "initial_score": 0.75,
    },
]


def test_auto_recall_tool_metadata() -> None:
    tool = create_auto_recall_evaluator_tool()
    assert tool.name == "evaluate_auto_recall_trigger"
    assert "auto_recall" in tool.description or "trigger" in tool.description.lower()


def test_auto_recall_tool_triggers_on_sensitive_event() -> None:
    config = RecallGateConfig(api_key_env_var="NON_EXISTENT_RERANKER_KEY_FOR_TEST", min_recall_score=0.5)
    gate = ExperienceRecallGate(config=config)
    tool = create_auto_recall_evaluator_tool(gate=gate)

    raw_result = tool.invoke(
        {
            "session_id": "sess-test-01",
            "current_turn": 1,
            "event_name": "task_start",
            "query_text": "Initialize code refactoring workspace",
            "candidates": SAMPLE_CANDIDATES,
        }
    )
    assert isinstance(raw_result, str)
    payload = json.loads(raw_result)

    assert payload["triggered"] is True
    assert payload["trigger_type"] == RecallTriggerType.TASK_START.value
    assert payload["candidates_pre_dedup"] == 2
    assert payload["candidates_post_dedup"] == 2
    assert len(payload["injected_memories"]) == 2
    assert payload["reranker_status"] == RerankerStatus.RERANKER_SKIPPED.value



def test_auto_recall_tool_suppresses_on_casual_chat() -> None:
    gate = ExperienceRecallGate()
    tool = create_auto_recall_evaluator_tool(gate=gate)

    raw_result = tool.invoke(
        {
            "session_id": "sess-test-01",
            "current_turn": 1,
            "query_text": "Good morning, how are you today?",
            "candidates": SAMPLE_CANDIDATES,
        }
    )
    payload = json.loads(raw_result)

    assert payload["triggered"] is False
    assert payload["trigger_type"] == RecallTriggerType.NONE.value
    assert len(payload["injected_memories"]) == 0


def test_auto_recall_sliding_window_deduplication() -> None:
    gate = ExperienceRecallGate(config=RecallGateConfig(dedup_turns=5, min_recall_score=0.5))
    tool = create_auto_recall_evaluator_tool(gate=gate)

    # Turn 1: Injects mem-01 and mem-02
    res_turn1 = json.loads(
        tool.invoke(
            {
                "session_id": "sess-dedup-01",
                "current_turn": 1,
                "event_name": "task_start",
                "candidates": SAMPLE_CANDIDATES,
            }
        )
    )
    assert res_turn1["candidates_post_dedup"] == 2
    assert len(res_turn1["injected_memories"]) == 2

    # Turn 2: Same candidates within 5 turns should be suppressed
    res_turn2 = json.loads(
        tool.invoke(
            {
                "session_id": "sess-dedup-01",
                "current_turn": 2,
                "event_name": "task_start",
                "candidates": SAMPLE_CANDIDATES,
            }
        )
    )
    assert res_turn2["candidates_post_dedup"] == 0
    assert len(res_turn2["injected_memories"]) == 0
    assert "suppressed by 5-turn dedup window" in res_turn2["audit_reason"]


def test_memory_manager_auto_recall_mixin() -> None:
    manager = DummyAutoRecallMemoryManager()
    gate = ExperienceRecallGate(config=RecallGateConfig(min_recall_score=0.5))

    raw_objs = [
        RecallCandidate(memory_id=c["memory_id"], content=c["content"], initial_score=c["initial_score"])
        for c in SAMPLE_CANDIDATES
    ]

    decision = manager.evaluate_auto_recall_decision(
        session_id="sess-mixin-01",
        current_turn=1,
        raw_candidates=raw_objs,
        event_name="task_start",
        gate=gate,
    )
    assert decision.triggered is True
    assert len(decision.injected_candidates) == 2

    seen = manager.get_auto_recall_seen_memories("sess-mixin-01", gate=gate)
    assert "mem-01" in seen
    assert "mem-02" in seen
