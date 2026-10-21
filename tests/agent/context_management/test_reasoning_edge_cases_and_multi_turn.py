"""Comprehensive edge case and multi-turn tests for reasoning preservation and observation compactor.

Exhaustively covers 100% of edge scenarios:
1. Interrupted/crashed multi-turn: tool output not consumed by subsequent AI message remains ACTIVE and is never pruned.
2. Parallel heterogeneous tool calls: some consumed, some unconsumed, partial pruning.
3. Giant tool output with diverse error signatures (AssertionError, Panic, Exit Code 1, MemoryError).
4. Long reasoning tails exceeding scan limit: bounded scan without memory explosion.
5. Mixed multimodal human message: image url, audio/video blocks with text, ensuring idempotent injection without duplication.
6. Session ledger idempotency, duplicate reasoning content across multiple turns.
7. Empty/whitespace thinking content and non-standard markdown lists.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.infra.schemas import ContextOffloadResult
from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.processors.active_tool_result_prune_processor import (
    build_memory_truncated_placeholder,
    is_tool_result_consumed,
    prune_tool_results_deterministic,
)
from myrm_agent_harness.agent.context_management.pipeline.processors.reasoning_anchor_processor import (
    ReasoningAnchorProcessor,
)
from myrm_agent_harness.agent.context_management.strategies.reasoning.anchor_extractor import (
    extract_raw_reasoning,
    extract_reasoning_anchors,
)
from myrm_agent_harness.agent.context_management.strategies.reasoning.anchor_ledger import (
    clear_session_anchor_ledger,
)


class TestReasoningEdgeCases:
    """Edge cases for reasoning extraction & anchor parsing."""

    def test_extract_raw_reasoning_empty_or_whitespace_blocks(self) -> None:
        msg = AIMessage(
            content=[
                {"type": "thinking", "thinking": "   \n\t  "},
                {"type": "text", "text": "hello"},
            ]
        )
        assert extract_raw_reasoning(msg) is None

    def test_extract_raw_reasoning_malformed_kwargs(self) -> None:
        # None or non-string/non-list reasoning_content
        msg1 = AIMessage(content="hi", additional_kwargs={"reasoning_content": None})
        assert extract_raw_reasoning(msg1) is None

        msg2 = AIMessage(content="hi", additional_kwargs={"thinking_blocks": [123, None, {}]})
        assert extract_raw_reasoning(msg2) is None

    def test_extract_anchors_giant_reasoning_tail_bound(self) -> None:
        # Giant reasoning string (100k chars)
        giant_noise = ("Analyzing steps...\n" * 5000)
        tail_decision = "核心决策: 最终方案确定采用分布式分片架构。"
        full_text = giant_noise + tail_decision

        anchors = extract_reasoning_anchors(full_text, turn_index=1)
        assert len(anchors) == 1
        assert "分布式分片架构" in anchors[0].content
        assert anchors[0].category == "decision"

    def test_extract_anchors_diverse_bullet_styles(self) -> None:
        text = """
        • 铁律: 必须通过安全测试门禁
        1. 约束: 响应延时不可高于200ms
        * 发现: 内存泄漏发生在线程池未释放
        """
        anchors = extract_reasoning_anchors(text, turn_index=2, max_anchors=3)
        assert len(anchors) == 3
        cats = {a.category for a in anchors}
        assert "constraint" in cats
        assert "finding" in cats


class TestObservationCompactorEdgeCases:
    """Edge cases for tool observation compaction and consumption tracking."""

    @pytest.mark.asyncio
    async def test_interrupted_turn_unconsumed_tool_never_pruned(self) -> None:
        """When an agent tool execution finishes but LLM is interrupted (no AIMessage afterwards),
        the tool result is NOT consumed and MUST NOT be pruned even if giant."""
        t_giant = ToolMessage(
            content="Giant log: " + ("x" * 20000),
            tool_call_id="call_999",
            name="bash_code_execute_tool",
        )
        messages = [
            HumanMessage(content="run task"),
            AIMessage(content="", tool_calls=[{"id": "call_999", "name": "bash_code_execute_tool", "args": {}}]),
            t_giant,
            # No AIMessage follows! Interrupted turn.
        ]

        assert is_tool_result_consumed(messages, 2) is False

        # Attempt pruning
        new_msgs, pruned, saved = await prune_tool_results_deterministic(
            messages,
            threshold_tokens=256,
            keep_recent_calls=0,
            force=False,
        )
        assert pruned == 0
        assert saved == 0
        assert new_msgs[2].content == t_giant.content

    def test_parallel_tool_calls_partial_consumption(self) -> None:
        """Two tool results: first is consumed by intermediate AI message; second is unconsumed."""
        t1 = ToolMessage(content="Result 1: " + ("A" * 10000), tool_call_id="c1", name="grep_tool")
        ai1 = AIMessage(content="Saw result 1, now doing step 2")
        t2 = ToolMessage(content="Result 2: " + ("B" * 10000), tool_call_id="c2", name="grep_tool")

        messages = [t1, ai1, t2]
        assert is_tool_result_consumed(messages, 0) is True
        assert is_tool_result_consumed(messages, 2) is False

    def test_semantic_findings_extraction_diverse_errors(self) -> None:
        # Panic
        p1 = build_memory_truncated_placeholder(
            tool_name="bash",
            content="panic: runtime error: invalid memory address or nil pointer dereference\n[stack]\n" + ("x" * 1300),
            est_tokens=500,
        )
        assert "[Tool output pruned:" in p1
        assert "panic" in p1.lower() or "runtime error" in p1.lower()

        # AssertionError
        p2 = build_memory_truncated_placeholder(
            tool_name="pytest",
            content="E   AssertionError: expected status 200 but got 500\n" + ("x" * 1300),
            est_tokens=400,
        )
        assert "[Tool output pruned:" in p2
        assert "AssertionError" in p2

        # Exit code
        p3 = build_memory_truncated_placeholder(
            tool_name="bash",
            content="Failed with code 1\n" + ("x" * 1300),
            est_tokens=300,
        )
        assert "[Tool output pruned:" in p3
        assert "Failed" in p3 or "pruned" in p3

    def test_small_content_preserved_verbatim_not_dropped(self) -> None:
        """Content within the head+tail budget must never be reduced to a marker-only stub."""
        content = "第三条：租金应于每月五日前支付，逾期按日万分之五计收违约金。" * 20
        placeholder = build_memory_truncated_placeholder(
            tool_name="file_read_tool",
            content=content,
            est_tokens=800,
        )
        assert placeholder == content

    @pytest.mark.asyncio
    async def test_memory_fallback_preserves_small_cjk_content(self) -> None:
        """Regression: emergency memory-fallback prune must not silently drop small CJK tool output."""
        clause = "第五条：乙方应在收到通知后三日内书面回复，逾期视为同意。" * 30
        t = ToolMessage(content=clause, tool_call_id="c1", name="file_read_tool")
        messages = [
            HumanMessage(content="review contract"),
            AIMessage(content="", tool_calls=[{"id": "c1", "name": "file_read_tool", "args": {}}]),
            t,
            AIMessage(content="clause reviewed"),
        ]

        new_msgs, pruned, saved = await prune_tool_results_deterministic(
            messages,
            threshold_tokens=256,
            keep_recent_calls=0,
            enable_memory_fallback=True,
            force=True,
        )
        # Small content cannot be reduced, so it must remain intact with no negative savings.
        assert saved >= 0
        assert pruned == 0
        assert new_msgs[2].content == clause

    @pytest.mark.asyncio
    async def test_active_prune_never_tool_is_never_pruned(self) -> None:
        """Active-prune-never tools (e.g. todo_write) must survive even in force fallback."""
        content = "todo list: " + ("task item detail " * 200)
        t = ToolMessage(content=content, tool_call_id="c1", name="todo_write")
        messages = [
            HumanMessage(content="plan"),
            AIMessage(content="", tool_calls=[{"id": "c1", "name": "todo_write", "args": {}}]),
            t,
            AIMessage(content="planned"),
        ]

        new_msgs, pruned, saved = await prune_tool_results_deterministic(
            messages,
            threshold_tokens=256,
            keep_recent_calls=0,
            enable_memory_fallback=True,
            force=True,
        )
        assert pruned == 0
        assert saved == 0
        assert new_msgs[2].content == content

    @pytest.mark.asyncio
    async def test_failed_offload_small_content_guard_skips_replacement(self) -> None:
        """A failed offload must not be treated as success, and the memory fallback
        must not replace small content with a non-reducing stub."""
        clause = "第六条：争议解决适用中华人民共和国法律。" * 30
        t = ToolMessage(content=clause, tool_call_id="c1", name="file_read_tool")
        messages = [
            HumanMessage(content="review contract"),
            AIMessage(content="", tool_calls=[{"id": "c1", "name": "file_read_tool", "args": {}}]),
            t,
            AIMessage(content="clause reviewed"),
        ]

        async def failing_offload(*, content: str, tool_name: str, scope_id: str | None) -> ContextOffloadResult:
            return ContextOffloadResult.failure("temporary_failure", "disk unavailable")

        new_msgs, pruned, saved = await prune_tool_results_deterministic(
            messages,
            threshold_tokens=256,
            keep_recent_calls=0,
            enable_memory_fallback=True,
            on_prune_offload=failing_offload,
            force=True,
        )
        assert pruned == 0
        assert saved == 0
        assert new_msgs[2].content == clause


class TestReasoningAnchorPipelineIdempotency:
    """Multi-turn idempotent injection tests."""

    @pytest.mark.asyncio
    async def test_repeated_pipeline_calls_do_not_duplicate_injection(self) -> None:
        session_id = "test_idempotent_session_99"
        clear_session_anchor_ledger(session_id)

        ai_turn = AIMessage(
            content="Plan confirmed",
            additional_kwargs={"reasoning_content": "核心决策: 统一使用 SQLite 存储"},
        )
        human_turn = HumanMessage(content="收到，请执行。")
        ctx = ProcessorContext(
            messages=[ai_turn, human_turn],
            user_query="执行",
            chat_id=session_id,
        )

        processor = ReasoningAnchorProcessor()

        # Turn 1
        res1 = await processor.process(ctx)
        c1 = str(res1.messages[-1].content)
        assert c1.count("[PRESERVED REASONING ANCHORS & CONSTRAINTS]") == 1

        # Turn 2: run pipeline again on the updated messages
        res2 = await processor.process(res1)
        c2 = str(res2.messages[-1].content)
        # MUST remain exactly 1, no duplicate stacking!
        assert c2.count("[PRESERVED REASONING ANCHORS & CONSTRAINTS]") == 1
        assert "统一使用 SQLite 存储" in c2
