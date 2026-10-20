"""Unit test suite for PromptCachePreservingEphemeralDeltaMemorySuite.

[INPUT]
myrm_agent_harness.agent.middlewares.memory_context.ephemeral_delta (POS: package under test)
langchain_core.messages::AIMessage, HumanMessage, SystemMessage (POS: message types)

[OUTPUT]
TestEphemeralDeltaSuite: 5 unit tests validating frozen prefix, human tail mounting,
conflict reconciliation, and post-session batch consolidation.

[POS]
Harness framework unit test for Item 98.
Strict typing applied: No `any` types allowed. Single file < 400 lines.
"""

from __future__ import annotations

import hashlib

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from myrm_agent_harness.agent.middlewares.memory_context.ephemeral_delta import (
    DeltaCategory,
    EphemeralDeltaRegistry,
    HumanTailDeltaInjector,
)


def test_record_delta_and_conflict_reconciliation() -> None:
    registry = EphemeralDeltaRegistry()
    session_id = "session_test_42"

    # Turn 1: user says test on port 8081
    registry.record_delta(
        session_id=session_id,
        key="test_port",
        value="8081",
        category=DeltaCategory.CONSTRAINT,
        turn_index=1,
    )
    assert len(registry.get_active_deltas(session_id)) == 1

    # Turn 3: user corrects port to 8082 (conflict reconciliation)
    registry.record_delta(
        session_id=session_id,
        key="test_port",
        value="8082",
        category=DeltaCategory.CORRECTION,
        turn_index=3,
    )

    active = registry.get_active_deltas(session_id)
    assert len(active) == 1
    assert active[0].value == "8082"
    assert active[0].turn_index == 3


def test_system_prompt_remains_100_percent_frozen() -> None:
    registry = EphemeralDeltaRegistry()
    injector = HumanTailDeltaInjector(registry)
    session_id = "session_frozen_prefix_99"

    raw_system_prompt = "You are Myrm Agent. User Profile: Senior Software Architect."
    initial_hash = hashlib.sha256(raw_system_prompt.encode("utf-8")).hexdigest()

    messages = [
        SystemMessage(content=raw_system_prompt),
        HumanMessage(content="Hello, please inspect my database."),
        AIMessage(content="Database inspected. All connections active."),
        HumanMessage(content="Please call me Old Zhang instead."),
    ]

    # Record delta during ongoing session
    registry.record_delta(
        session_id=session_id,
        key="user_nickname",
        value="Old Zhang",
        category=DeltaCategory.PREFERENCE,
        turn_index=2,
    )

    processed_messages, metrics = injector.inject_deltas(messages, session_id)

    # 1. System prompt MUST remain 100% frozen
    assert metrics.system_prompt_frozen is True
    assert metrics.system_prompt_byte_hash == initial_hash
    assert processed_messages[0].content == raw_system_prompt

    # 2. KV Cache ratio should be 1.0 (no prefix cache broken)
    assert metrics.kv_cache_hit_ratio >= 0.98
    assert metrics.in_flight_deltas_count == 1
    assert metrics.avoided_recomputation_tokens > 0


def test_human_tail_mounting_and_recency_override() -> None:
    registry = EphemeralDeltaRegistry()
    injector = HumanTailDeltaInjector(registry)
    session_id = "session_recency_override_101"

    registry.record_delta(
        session_id=session_id,
        key="response_language",
        value="zh-CN",
        category=DeltaCategory.PREFERENCE,
        turn_index=2,
    )

    messages = [
        SystemMessage(content="System instruction base"),
        HumanMessage(content="First turn human prompt"),
        AIMessage(content="First turn AI answer"),
        HumanMessage(content="Second turn human prompt"),
    ]

    processed, _ = injector.inject_deltas(messages, session_id)

    # First HumanMessage must not be contaminated
    assert "<ephemeral_session_deltas>" not in str(processed[1].content)

    # Final HumanMessage must carry the tail tag
    final_human_content = str(processed[3].content)
    assert "Second turn human prompt" in final_human_content
    assert "<ephemeral_session_deltas>" in final_human_content
    assert 'response_language -> "zh-CN"' in final_human_content


def test_batch_consolidation_plan_and_commit() -> None:
    registry = EphemeralDeltaRegistry()
    session_id = "session_consolidation_88"

    registry.record_delta(session_id, "nickname", "Boss", turn_index=1)
    registry.record_delta(session_id, "env", "staging", turn_index=2)

    plan = registry.generate_consolidation_plan(session_id)
    assert len(plan.deltas_to_commit) == 2
    assert "nickname" in plan.superseded_keys
    assert "env" in plan.superseded_keys
    assert plan.total_tokens_saved > 0

    # Mark consolidated
    committed_count = registry.mark_consolidated(session_id)
    assert committed_count == 2
    assert len(registry.get_active_deltas(session_id)) == 0


def test_empty_deltas_produces_no_tail_mutation() -> None:
    registry = EphemeralDeltaRegistry()
    injector = HumanTailDeltaInjector(registry)
    session_id = "session_empty_deltas"

    messages = [
        SystemMessage(content="System instruction"),
        HumanMessage(content="Pure human prompt"),
    ]

    processed, metrics = injector.inject_deltas(messages, session_id)
    assert processed[1].content == "Pure human prompt"
    assert metrics.in_flight_deltas_count == 0
