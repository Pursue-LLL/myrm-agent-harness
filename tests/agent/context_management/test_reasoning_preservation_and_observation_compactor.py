"""Unit tests for reasoning preservation and observation compaction.

Verifies:
1. Multi-provider raw reasoning extraction (Anthropic, DeepSeek/MiMo, OpenAI Responses, inline think tags).
2. Deterministic decision anchor mining & immutable session ledger bounded retention.
3. ReasoningAnchorProcessor pipeline integration and prompt cache friendly injection.
4. Consumption-aware tool observation pruning & multimodal media pointer isolation.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.processors.active_tool_result_prune_processor import (
    build_memory_truncated_placeholder,
    is_tool_result_consumed,
    prune_tool_results_deterministic,
    sanitize_multimodal_content,
)
from myrm_agent_harness.agent.context_management.pipeline.processors.reasoning_anchor_processor import (
    ReasoningAnchorProcessor,
)
from myrm_agent_harness.agent.context_management.strategies.compactor.tool_stats import extract_tool_stats
from myrm_agent_harness.agent.context_management.strategies.reasoning.anchor_extractor import (
    ReasoningAnchor,
    extract_raw_reasoning,
    extract_reasoning_anchors,
)
from myrm_agent_harness.agent.context_management.strategies.reasoning.anchor_ledger import (
    SessionAnchorLedger,
    clear_session_anchor_ledger,
    get_session_anchor_ledger,
)


class TestReasoningAnchorExtractor:
    """Verify multi-provider reasoning extraction and anchor mining."""

    def test_extract_raw_reasoning_anthropic_blocks(self) -> None:
        msg = AIMessage(
            content=[
                {"type": "thinking", "thinking": "Let's think step by step."},
                {"type": "text", "text": "Final response."},
            ]
        )
        extracted = extract_raw_reasoning(msg)
        assert extracted == "Let's think step by step."

    def test_extract_raw_reasoning_deepseek_kwargs(self) -> None:
        msg = AIMessage(
            content="Hello",
            additional_kwargs={"reasoning_content": "DeepSeek internal reasoning chain."},
        )
        extracted = extract_raw_reasoning(msg)
        assert extracted == "DeepSeek internal reasoning chain."

    def test_extract_raw_reasoning_inline_think_tags(self) -> None:
        msg = AIMessage(content="<think>Inline thinking content here.</think>\nActual reply.")
        extracted = extract_raw_reasoning(msg)
        assert extracted == "Inline thinking content here."

    def test_extract_raw_reasoning_openai_responses_items(self) -> None:
        msg = AIMessage(
            content="Result",
            additional_kwargs={
                "responses_reasoning_items": [
                    {"summary": "Evaluated schema and chosen strategy A."}
                ]
            },
        )
        extracted = extract_raw_reasoning(msg)
        assert "Evaluated schema and chosen strategy A." in (extracted or "")

    def test_extract_raw_reasoning_thinking_blocks_dicts_and_strings(self) -> None:
        msg = AIMessage(
            content="",
            additional_kwargs={
                "thinking_blocks": [
                    "raw string thought",
                    {"type": "thinking", "thinking": "dict thought"},
                ]
            },
        )
        extracted = extract_raw_reasoning(msg)
        assert "raw string thought" in (extracted or "")
        assert "dict thought" in (extracted or "")

    def test_extract_raw_reasoning_none_cases(self) -> None:
        msg1 = AIMessage(content="Just a normal text without thinking.")
        assert extract_raw_reasoning(msg1) is None
        assert extract_reasoning_anchors(None) == []
        assert extract_reasoning_anchors("   \n\n  ") == []

    def test_extract_decision_anchors_conclusive_fallback(self) -> None:
        # No explicit prefix, should trigger conclusive fallback
        raw_reasoning = "We have explored multiple paths. Ultimately, using sqlite wal mode solved all concurrency issues."
        anchors = extract_reasoning_anchors(raw_reasoning, turn_index=5, max_anchors=1)
        assert len(anchors) == 1
        assert anchors[0].category == "finding"
        assert "sqlite wal mode solved all concurrency issues" in anchors[0].content

    def test_extract_decision_anchors_with_explicit_patterns(self) -> None:
        reasoning = (
            "We have two options: JWT or Session.\n"
            "- 决策: 采用 JWT 内部归一化，严禁修改外部接口签名\n"
            "- 铁律: 禁止跨客户端复制 bundle\n"
            "- 根因定位: 缺少对 tool_call_id 的空值校验"
        )
        anchors = extract_reasoning_anchors(reasoning, turn_index=1, max_anchors=3)
        assert len(anchors) == 3
        categories = {a.category for a in anchors}
        assert "decision" in categories
        assert "constraint" in categories
        assert "finding" in categories
        assert any("JWT" in a.content for a in anchors)
        assert any("跨客户端" in a.content for a in anchors)


class TestSessionAnchorLedger:
    """Verify ledger retention, deduplication, and context rendering."""

    def test_ledger_record_and_bounded_capacity(self) -> None:
        ledger = SessionAnchorLedger("test_session_1", max_anchors=2)
        anc1 = ReasoningAnchor("a1", 1, "decision", "Decision 1")
        anc2 = ReasoningAnchor("a2", 2, "constraint", "Constraint 2")
        anc3 = ReasoningAnchor("a3", 3, "finding", "Finding 3")

        ledger.record_anchor(anc1)
        ledger.record_anchor(anc2)
        assert len(ledger.get_anchors()) == 2

        # FIFO eviction
        ledger.record_anchor(anc3)
        anchors = ledger.get_anchors()
        assert len(anchors) == 2
        assert anchors[0].anchor_id == "a2"
        assert anchors[1].anchor_id == "a3"

    def test_ledger_deduplication(self) -> None:
        ledger = SessionAnchorLedger("test_session_2", max_anchors=5)
        anc1 = ReasoningAnchor("a1", 1, "decision", "Duplicate content")
        anc2 = ReasoningAnchor("a2", 2, "decision", "Duplicate content")

        ledger.record_anchor(anc1)
        ledger.record_anchor(anc2)
        assert len(ledger.get_anchors()) == 1

    def test_ledger_filter_and_clear(self) -> None:
        ledger = SessionAnchorLedger("test_session_ops", max_anchors=10)
        anc1 = ReasoningAnchor("a1", 1, "decision", "Decision 1")
        anc2 = ReasoningAnchor("a2", 2, "constraint", "Constraint 2")
        ledger.record_anchors([anc1, anc2])

        assert len(ledger.get_anchors(category="decision")) == 1
        assert len(ledger.get_anchors(category="constraint")) == 1
        assert len(ledger.get_anchors(category="non_existent")) == 0
        rendered = ledger.render_anchors_context(max_count=1)
        assert "Constraint 2" in rendered

        ledger.clear()
        assert len(ledger.get_anchors()) == 0
        assert ledger.render_anchors_context() == ""

    def test_global_session_eviction(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.reasoning.anchor_ledger import (
            _SESSION_LEDGERS,
            get_session_anchor_ledger,
        )
        # Create many sessions to trigger bounded eviction
        for i in range(550):
            get_session_anchor_ledger(f"bulk_session_{i}")
        assert len(_SESSION_LEDGERS) <= 500


class TestReasoningAnchorProcessor:
    """Verify pipeline integration and prompt cache preservation."""

    @pytest.mark.asyncio
    async def test_pipeline_extracts_and_injects_anchors(self) -> None:
        session_id = "test_pipe_session"
        clear_session_anchor_ledger(session_id)

        ai_msg = AIMessage(
            content="I will fix this.",
            additional_kwargs={
                "reasoning_content": "分析完毕。\n- 核心结论: 数据库连接必须增加重试机制"
            },
        )
        human_msg = HumanMessage(content="Please proceed with the implementation.")
        ctx = ProcessorContext(
            messages=[human_msg, ai_msg, HumanMessage(content="Next step?")],
            user_query="implement retry",
            chat_id=session_id,
        )

        processor = ReasoningAnchorProcessor()
        assert await processor.should_process(ctx) is True

        res = await processor.process(ctx)
        # Verify metadata
        assert "active_reasoning_anchors" in res.metadata
        assert len(res.metadata["active_reasoning_anchors"]) >= 1

        # Verify injection into last HumanMessage
        last_human = res.messages[-1]
        assert isinstance(last_human, HumanMessage)
        assert "[PRESERVED REASONING ANCHORS & CONSTRAINTS]" in str(last_human.content)
        assert "数据库连接必须增加重试机制" in str(last_human.content)

    @pytest.mark.asyncio
    async def test_pipeline_multimodal_human_message_injection(self) -> None:
        session_id = "test_pipe_multimodal_session"
        clear_session_anchor_ledger(session_id)

        ai_msg = AIMessage(
            content="Plan approved.",
            additional_kwargs={
                "reasoning_content": "- 铁律: 禁止跨客户bundle复制"
            },
        )
        human_msg = HumanMessage(
            content=[
                {"type": "text", "text": "Check this screenshot."},
                {"type": "image_url", "image_url": "data:image/png;base64,xxxx"},
            ]
        )
        ctx = ProcessorContext(
            messages=[ai_msg, human_msg],
            user_query="inspect",
            chat_id=session_id,
        )
        processor = ReasoningAnchorProcessor()
        res = await processor.process(ctx)

        last_human = res.messages[-1]
        assert isinstance(last_human.content, list)
        text_blocks = [b for b in last_human.content if isinstance(b, dict) and b.get("type") == "text"]
        assert any("禁止跨客户bundle复制" in str(b.get("text")) for b in text_blocks)


class TestConsumptionAwareCompaction:
    """Verify tool consumption state tracking and semantic observation cards."""

    def test_is_tool_result_consumed(self) -> None:
        t1 = ToolMessage(content="res1", tool_call_id="c1")
        ai1 = AIMessage(content="acknowledged")
        t2 = ToolMessage(content="res2", tool_call_id="c2")

        # t1 is followed by ai1 -> consumed
        messages = [t1, ai1, t2]
        assert is_tool_result_consumed(messages, 0) is True
        # t2 is not followed by any AIMessage -> active (not consumed)
        assert is_tool_result_consumed(messages, 2) is False

    def test_sanitize_multimodal_content(self) -> None:
        raw_blocks = [
            {"type": "text", "text": "Screenshot captured:"},
            {"type": "image_url", "image_url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg..."},
        ]
        sanitized, has_media = sanitize_multimodal_content(raw_blocks)
        assert has_media is True
        assert isinstance(sanitized, str)
        assert "[IMAGE_OMITTED_MEDIA_POINTER:" in sanitized
        assert "Screenshot captured:" in sanitized

    def test_build_memory_truncated_placeholder_with_semantic_finding(self) -> None:
        content = "Line 1\nTraceback (most recent call last):\n  File 'a.py'\nZeroDivisionError: division by zero\n" + ("x" * 2000)
        ph = build_memory_truncated_placeholder(
            tool_name="bash_code_execute_tool",
            content=content,
            est_tokens=600,
        )
        assert "[Tool output pruned:" in ph
        assert "Finding:" in ph
        assert "Traceback" in ph or "division by zero" in ph

    def test_extract_tool_stats_semantic_enhancements(self) -> None:
        tool_content = "def calculate_tax():\n    pass\nclass InvoiceProcessor:\n    pass\n"
        stats = extract_tool_stats("file_read_tool", tool_content)
        assert "InvoiceProcessor" in str(stats.get("findings"))
