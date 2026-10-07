"""Unit tests for Dialogue State Machine and Adaptive Context Optimizer.

Part of Item 128: DialogueStateMachineAndPerStateAdaptiveContextOptimizationEngine.
Verifies 6-state classification, coreference-aware topic drift detection,
two-tier token governance (warning chatter pruning, hard limit isolation), and concurrency.
"""

from __future__ import annotations

import concurrent.futures

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from myrm_agent_harness.runtime.context.dialogue_state_machine_engine import (
    AdaptiveContextOptimizer,
    DialogueStateMachine,
)
from myrm_agent_harness.runtime.context.dialogue_state_machine_types import (
    AdaptiveDialogueOptimizationConfig,
    DialogueStateKind,
    TokenGovernanceThresholdTier,
)


def test_six_canonical_dialogue_states_classification() -> None:
    """Verify that all 6 canonical interaction states are accurately classified."""
    config = AdaptiveDialogueOptimizationConfig()
    sm = DialogueStateMachine(config=config)

    # 1. INITIAL_INQUIRY (turn 1 onset)
    ann1 = sm.classify_turn_state(
        current_input="Build a high performance rust SQLite extension",
        turn_index=1,
        messages=[],
    )
    assert ann1.state_kind == DialogueStateKind.INITIAL_INQUIRY
    assert not ann1.topic_drift.is_drift_detected

    # 2. FOLLOW_UP_PROBE (turn 2 with pronoun anchor referencing prior turn)
    messages = [
        HumanMessage(content="Build a high performance rust SQLite extension"),
        AIMessage(content="Here is the project structure using cargo-pgrx/rusqlite."),
    ]
    ann2 = sm.classify_turn_state(
        current_input="How does this extension handle multi-threaded connection pooling?",
        turn_index=2,
        messages=messages,
    )
    assert ann2.state_kind == DialogueStateKind.FOLLOW_UP_PROBE
    assert not ann2.topic_drift.is_drift_detected

    # 3. REQUIREMENT_SUPPLEMENT (explicit supplement keywords)
    ann3 = sm.classify_turn_state(
        current_input="另外补充一个要求：必须支持 WASM 编译环境并在内存虚拟文件系统中运行",
        turn_index=3,
        messages=messages,
    )
    assert ann3.state_kind == DialogueStateKind.REQUIREMENT_SUPPLEMENT

    # 4. CLARIFICATION_DISAMBIGUATION (previous assistant turn asked a clarifying question)
    messages_with_question = [
        HumanMessage(content="Deploy to production cloud"),
        AIMessage(content="请问您希望部署到 AWS ECS 还是 Cloudflare Workers？"),
    ]
    ann4 = sm.classify_turn_state(
        current_input="选择 Cloudflare Workers 平台",
        turn_index=4,
        messages=messages_with_question,
    )
    assert ann4.state_kind == DialogueStateKind.CLARIFICATION_DISAMBIGUATION

    # 5. TOPIC_SWITCH (drastic semantic jump with no coreference anchors)
    messages_db = [
        HumanMessage(content="Postgres relational schema database index optimization"),
        AIMessage(content="Indexes created on foreign keys."),
    ]
    ann5 = sm.classify_turn_state(
        current_input="明天北京和上海的天气预报气温是多少度？",
        turn_index=5,
        messages=messages_db,
    )
    assert ann5.state_kind == DialogueStateKind.TOPIC_SWITCH
    assert ann5.topic_drift.is_drift_detected
    assert ann5.topic_drift.recommended_action == "SOFT_ISOLATE"

    # 6. SESSION_TERMINAL (closure keywords)
    ann6 = sm.classify_turn_state(
        current_input="搞定了，谢谢完成！",
        turn_index=6,
        messages=messages_db,
    )
    assert ann6.state_kind == DialogueStateKind.SESSION_TERMINAL


def test_coreference_pronoun_anchor_drift_suppression() -> None:
    """Verify pronouns (e.g. '这款', 'it') prevent false positive topic drift."""
    sm = DialogueStateMachine()
    # Prior topic: laptop specifications
    prior_turn = "MacBook Pro M3 Max 128GB unified memory performance benchmarks"
    # Current turn has zero word overlap except pronoun anchor '这款'
    current_turn = "这款在执行长程复杂任务编译时的真实续航表现如何？"

    drift = sm.assess_topic_drift(current_turn, prior_turn)
    # Pronoun suppresses drift to ensure coreference continuity
    assert not drift.is_drift_detected
    assert drift.recommended_action == "MAINTAIN_THREAD"


def test_two_tier_token_governance_optimization() -> None:
    """Verify warning chatter pruning and hard-limit topic compaction tiers."""
    config = AdaptiveDialogueOptimizationConfig(
        warning_token_threshold=50,  # low threshold for unit test verification
        limit_token_threshold=150,
    )
    optimizer = AdaptiveContextOptimizer(config=config)

    # 1. Tier 1: Warning threshold reached -> Prune conversational chatter
    messages_with_chatter = [
        SystemMessage(content="You are an expert system agent."),
        HumanMessage(content="Plan database migration."),
        AIMessage(content="Plan created."),
        HumanMessage(content="好的"),  # chatter
        AIMessage(content="Proceeding..."),
        HumanMessage(content="ok"),  # chatter
        AIMessage(content="Done."),
        HumanMessage(content="Check table constraints."),
    ]

    opt_msgs, res = optimizer.optimize_context(
        messages=messages_with_chatter,
        current_input="Please run validation scripts",
        turn_index=8,
    )
    assert res.governance_tier in (TokenGovernanceThresholdTier.WARNING_PRUNE, TokenGovernanceThresholdTier.LIMIT_COMPACT)
    assert res.pruned_chatter_count >= 1
    # Chatter messages "好的" and "ok" pruned
    contents = [str(m.content) for m in opt_msgs]
    assert "好的" not in contents
    assert "ok" not in contents


def test_limit_compact_and_topic_drift_soft_isolation() -> None:
    """Verify that hitting the limit threshold or topic switch isolates preceding turns."""
    config = AdaptiveDialogueOptimizationConfig(
        warning_token_threshold=20,
        limit_token_threshold=40,
    )
    optimizer = AdaptiveContextOptimizer(config=config)

    messages = [
        SystemMessage(content="Core system instructions."),
        HumanMessage(content="Turn 1: Initial core requirement."),
        AIMessage(content="Turn 2: Response analysis."),
        HumanMessage(content="Turn 3: Middle details."),
        AIMessage(content="Turn 4: Middle result."),
        HumanMessage(content="Turn 5: Middle continuation."),
        AIMessage(content="Turn 6: Pre-shift answer."),
    ]

    # Topic switch triggers soft isolation
    opt_msgs, res = optimizer.optimize_context(
        messages=messages,
        current_input="明天天气预报下雨吗？",
        turn_index=7,
    )
    assert res.isolated_prior_topics_count > 0
    # Head and tail preserved with isolation marker
    assert isinstance(opt_msgs[0], SystemMessage)
    marker_found = any("<topic_drift_isolated" in str(m.content) for m in opt_msgs)
    assert marker_found


def test_multithreaded_concurrency_safety() -> None:
    """Verify thread-safe classification and optimization under concurrent load."""
    optimizer = AdaptiveContextOptimizer()

    def task(worker_id: int) -> None:
        msgs = [
            SystemMessage(content="System"),
            HumanMessage(content=f"Worker {worker_id} query"),
            AIMessage(content=f"Worker {worker_id} answer"),
        ]
        for step in range(10):
            _, res = optimizer.optimize_context(
                messages=msgs,
                current_input=f"Worker {worker_id} turn {step} follow-up",
                turn_index=step + 1,
            )
            assert res.current_annotation.turn_index == step + 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(task, i) for i in range(16)]
        concurrent.futures.wait(futures)
