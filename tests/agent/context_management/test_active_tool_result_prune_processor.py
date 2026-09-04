"""Tests for ActiveToolResultPruneProcessor."""

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.infra.retention_helpers import (
    find_keep_recent_prune_cutoff,
)
from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.processors.active_tool_result_prune_processor import (
    ActiveToolResultPruneProcessor,
)


def _build_context(
    messages: list,
    metadata: dict | None = None,
    chat_id: str = "test-chat",
) -> ProcessorContext:
    return ProcessorContext(
        messages=messages,
        user_query="test",
        chat_id=chat_id,
        metadata=metadata or {},
        merged_context={},
    )


def _large_content(tokens: int = 3000) -> str:
    """Generate content that estimates to roughly the given token count."""
    return "x " * (tokens * 4)


def _make_tool_msg(content: str, name: str = "grep_tool", tool_call_id: str = "tc1") -> ToolMessage:
    return ToolMessage(content=content, name=name, tool_call_id=tool_call_id)


def _make_ai_msg(tool_calls: list[dict] | None = None) -> AIMessage:
    return AIMessage(
        content="thinking...",
        tool_calls=tool_calls or [{"id": "tc1", "name": "grep_tool", "args": {}}],
    )


class TestFindKeepRecentPruneCutoff:
    def test_no_groups(self):
        messages = [HumanMessage(content="hi")]
        assert find_keep_recent_prune_cutoff(messages, keep_recent_calls=5) == 0

    def test_single_step(self):
        messages = [
            HumanMessage(content="hi"),
            _make_ai_msg(),
            _make_tool_msg("result"),
        ]
        assert find_keep_recent_prune_cutoff(messages, keep_recent_calls=5) == 2

    def test_two_steps_both_protected(self):
        messages = [
            HumanMessage(content="hi"),
            _make_ai_msg([{"id": "tc1", "name": "grep_tool", "args": {}}]),
            _make_tool_msg("result1", tool_call_id="tc1"),
            _make_ai_msg([{"id": "tc2", "name": "web_search", "args": {}}]),
            _make_tool_msg("result2", name="web_search", tool_call_id="tc2"),
        ]
        assert find_keep_recent_prune_cutoff(messages, keep_recent_calls=5) == 2


class TestShouldProcess:
    @pytest.mark.asyncio
    async def test_skip_when_too_few_messages(self):
        proc = ActiveToolResultPruneProcessor(threshold_tokens=100)
        ctx = _build_context([HumanMessage(content="hi")])
        assert await proc.should_process(ctx) is False

    @pytest.mark.asyncio
    async def test_skip_on_resume(self):
        proc = ActiveToolResultPruneProcessor(threshold_tokens=100)
        ctx = _build_context(
            [
                HumanMessage(content="hi"),
                _make_ai_msg(),
                _make_tool_msg("r"),
                _make_ai_msg(),
            ]
        )
        ctx.is_resume = True
        assert await proc.should_process(ctx) is False

    @pytest.mark.asyncio
    async def test_skip_when_disabled_via_metadata(self):
        proc = ActiveToolResultPruneProcessor(threshold_tokens=100)
        ctx = _build_context(
            [
                HumanMessage(content="hi"),
                _make_ai_msg(),
                _make_tool_msg("r"),
                _make_ai_msg(),
            ],
            metadata={"enable_active_tool_prune": False},
        )
        assert await proc.should_process(ctx) is False

    @pytest.mark.asyncio
    async def test_should_process_with_enough_messages(self):
        proc = ActiveToolResultPruneProcessor(threshold_tokens=100)
        ctx = _build_context(
            [
                HumanMessage(content="hi"),
                _make_ai_msg(),
                _make_tool_msg("r"),
                _make_ai_msg(),
            ]
        )
        assert await proc.should_process(ctx) is True


class TestProcess:
    @pytest.mark.asyncio
    async def test_prune_large_earlier_result_outside_keep_recent(self):
        offload = AsyncMock(return_value="/archive/test.gz")
        proc = ActiveToolResultPruneProcessor(threshold_tokens=100, keep_recent_calls=2, on_prune_offload=offload)
        large = _large_content(3000)
        messages = [HumanMessage(content="hi")]
        for i in range(3):
            tc_id = f"tc{i}"
            messages.extend(
                [
                    _make_ai_msg([{"id": tc_id, "name": "grep_tool", "args": {}}]),
                    _make_tool_msg(large if i == 0 else "small", tool_call_id=tc_id),
                ]
            )
        ctx = _build_context(messages)
        result = await proc.process(ctx)

        assert result.tokens_saved > 0
        assert "[Tool result archived" in result.messages[2].content
        offload.assert_called_once()

    @pytest.mark.asyncio
    async def test_keep_recent_protects_earlier_step_within_window(self):
        offload = AsyncMock(return_value="/archive/test.gz")
        proc = ActiveToolResultPruneProcessor(threshold_tokens=100, keep_recent_calls=5, on_prune_offload=offload)
        large = _large_content(3000)
        messages = [
            HumanMessage(content="hi"),
            _make_ai_msg([{"id": "tc1", "name": "grep_tool", "args": {}}]),
            _make_tool_msg(large, tool_call_id="tc1"),
            _make_ai_msg([{"id": "tc2", "name": "web_search", "args": {}}]),
            _make_tool_msg("small result", name="web_search", tool_call_id="tc2"),
        ]
        ctx = _build_context(messages)
        result = await proc.process(ctx)

        assert result.tokens_saved == 0
        assert large.split()[0] in result.messages[2].content
        offload.assert_not_called()

    @pytest.mark.asyncio
    async def test_recent_file_read_not_pruned(self):
        offload = AsyncMock(return_value="/archive/test.gz")
        proc = ActiveToolResultPruneProcessor(
            threshold_tokens=100,
            keep_recent_calls=5,
            on_prune_offload=offload,
        )
        large = _large_content(3000)
        messages = [
            HumanMessage(content="hi"),
            _make_ai_msg([{"id": "tc1", "name": "file_read_tool", "args": {}}]),
            _make_tool_msg(large, name="file_read_tool", tool_call_id="tc1"),
            _make_ai_msg([{"id": "tc2", "name": "web_search", "args": {}}]),
            _make_tool_msg("small", name="web_search", tool_call_id="tc2"),
        ]
        ctx = _build_context(messages)
        result = await proc.process(ctx)

        assert result.tokens_saved == 0
        offload.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_small_results(self):
        offload = AsyncMock(return_value="/archive/test.gz")
        proc = ActiveToolResultPruneProcessor(threshold_tokens=5000, on_prune_offload=offload)
        messages = [
            HumanMessage(content="hi"),
            _make_ai_msg([{"id": "tc1", "name": "grep_tool", "args": {}}]),
            _make_tool_msg("small result", tool_call_id="tc1"),
            _make_ai_msg([{"id": "tc2", "name": "web_search", "args": {}}]),
            _make_tool_msg("also small", name="web_search", tool_call_id="tc2"),
        ]
        ctx = _build_context(messages)
        result = await proc.process(ctx)

        assert result.tokens_saved == 0
        offload.assert_not_called()

    @pytest.mark.asyncio
    async def test_latest_step_not_pruned(self):
        offload = AsyncMock(return_value="/archive/test.gz")
        proc = ActiveToolResultPruneProcessor(threshold_tokens=100, on_prune_offload=offload)
        large = _large_content(3000)
        messages = [
            HumanMessage(content="hi"),
            _make_ai_msg([{"id": "tc1", "name": "grep_tool", "args": {}}]),
            _make_tool_msg(large, tool_call_id="tc1"),
        ]
        ctx = _build_context(messages)
        result = await proc.process(ctx)

        assert result.tokens_saved == 0
        offload.assert_not_called()

    @pytest.mark.asyncio
    async def test_fail_safe_on_offload_error(self):
        offload = AsyncMock(side_effect=RuntimeError("disk full"))
        proc = ActiveToolResultPruneProcessor(threshold_tokens=100, on_prune_offload=offload)
        large = _large_content(3000)
        original_content = large
        messages = [
            HumanMessage(content="hi"),
            _make_ai_msg([{"id": "tc1", "name": "grep_tool", "args": {}}]),
            _make_tool_msg(large, tool_call_id="tc1"),
            _make_ai_msg([{"id": "tc2", "name": "web_search", "args": {}}]),
            _make_tool_msg("small", name="web_search", tool_call_id="tc2"),
        ]
        ctx = _build_context(messages)
        result = await proc.process(ctx)

        assert result.tokens_saved == 0
        assert result.messages[2].content == original_content

    @pytest.mark.asyncio
    async def test_no_prune_without_offload_callback(self):
        proc = ActiveToolResultPruneProcessor(threshold_tokens=100, keep_recent_calls=1)
        large = _large_content(3000)
        messages = [HumanMessage(content="hi")]
        for i in range(3):
            tc_id = f"tc{i}"
            messages.extend(
                [
                    _make_ai_msg([{"id": tc_id, "name": "grep_tool", "args": {}}]),
                    _make_tool_msg(large if i == 0 else "small", tool_call_id=tc_id),
                ]
            )
        ctx = _build_context(messages)
        result = await proc.process(ctx)

        assert result.tokens_saved == 0
        assert large.split()[0] in result.messages[2].content

    @pytest.mark.asyncio
    async def test_placeholder_cache_reuse(self):
        call_count = 0

        async def counting_offload(*, content, tool_name, scope_id):
            nonlocal call_count
            call_count += 1
            return f"/archive/test_{call_count}.gz"

        proc = ActiveToolResultPruneProcessor(
            threshold_tokens=100,
            keep_recent_calls=1,
            on_prune_offload=counting_offload,
        )
        large = _large_content(3000)
        messages = [
            HumanMessage(content="hi"),
            _make_ai_msg([{"id": "tc1", "name": "grep_tool", "args": {}}]),
            _make_tool_msg(large, tool_call_id="tc1"),
            _make_ai_msg([{"id": "tc2", "name": "web_search", "args": {}}]),
            _make_tool_msg("small", name="web_search", tool_call_id="tc2"),
        ]
        ctx = _build_context(messages)
        await proc.process(ctx)
        assert call_count == 1

        messages2 = [
            HumanMessage(content="hi"),
            _make_ai_msg([{"id": "tc1", "name": "grep_tool", "args": {}}]),
            _make_tool_msg(large, tool_call_id="tc1"),
            _make_ai_msg([{"id": "tc2", "name": "web_search", "args": {}}]),
            _make_tool_msg("second small", name="web_search", tool_call_id="tc2"),
            _make_ai_msg([{"id": "tc3", "name": "bash_tool", "args": {}}]),
            _make_tool_msg("third", name="bash_tool", tool_call_id="tc3"),
        ]
        ctx2 = _build_context(messages2)
        result2 = await proc.process(ctx2)

        assert call_count == 1
        assert result2.tokens_saved > 0

    @pytest.mark.asyncio
    async def test_early_return_when_no_prunable_groups(self):
        proc = ActiveToolResultPruneProcessor(threshold_tokens=100)
        ctx = _build_context([HumanMessage(content="only human")])
        result = await proc.process(ctx)
        assert result.tokens_saved == 0

    @pytest.mark.asyncio
    async def test_skip_multimodal_tool_content(self):
        offload = AsyncMock(return_value="/archive/test.gz")
        proc = ActiveToolResultPruneProcessor(threshold_tokens=100, keep_recent_calls=1, on_prune_offload=offload)
        large = _large_content(3000)
        tool_msg = _make_tool_msg(large, tool_call_id="tc1")
        tool_msg.content = [{"type": "text", "text": large}]
        messages = [
            HumanMessage(content="hi"),
            _make_ai_msg([{"id": "tc1", "name": "grep_tool", "args": {}}]),
            tool_msg,
            _make_ai_msg([{"id": "tc2", "name": "web_search", "args": {}}]),
            _make_tool_msg("small", name="web_search", tool_call_id="tc2"),
        ]
        ctx = _build_context(messages)
        result = await proc.process(ctx)
        assert isinstance(result.messages[2].content, list)
        offload.assert_not_called()

    @pytest.mark.asyncio
    async def test_offload_failure_result_preserves_original(self):
        offload = AsyncMock(return_value={"success": False, "path": None})
        proc = ActiveToolResultPruneProcessor(threshold_tokens=100, keep_recent_calls=1, on_prune_offload=offload)
        large = _large_content(3000)
        messages = [
            HumanMessage(content="hi"),
            _make_ai_msg([{"id": "tc1", "name": "grep_tool", "args": {}}]),
            _make_tool_msg(large, tool_call_id="tc1"),
            _make_ai_msg([{"id": "tc2", "name": "web_search", "args": {}}]),
            _make_tool_msg("small", name="web_search", tool_call_id="tc2"),
        ]
        ctx = _build_context(messages)
        result = await proc.process(ctx)
        assert result.messages[2].content == large
        assert result.tokens_saved == 0

    @pytest.mark.asyncio
    async def test_records_task_metrics_when_prune_succeeds(self):
        offload = AsyncMock(return_value="/archive/test.gz")
        proc = ActiveToolResultPruneProcessor(threshold_tokens=100, keep_recent_calls=1, on_prune_offload=offload)
        large = _large_content(3000)
        messages = [
            HumanMessage(content="hi"),
            _make_ai_msg([{"id": "tc1", "name": "grep_tool", "args": {}}]),
            _make_tool_msg(large, tool_call_id="tc1"),
            _make_ai_msg([{"id": "tc2", "name": "web_search", "args": {}}]),
            _make_tool_msg("small", name="web_search", tool_call_id="tc2"),
        ]
        ctx = _build_context(messages, chat_id="metrics-chat")

        class FakeMetrics:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def record_compression(self, **kwargs: object) -> None:
                self.calls.append(kwargs)

        fake_metrics = FakeMetrics()
        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.active_tool_result_prune_processor.get_task_metrics",
            return_value=fake_metrics,
        ):
            result = await proc.process(ctx)

        assert result.tokens_saved > 0
        assert len(fake_metrics.calls) == 1
        assert fake_metrics.calls[0]["compression_type"] == "active_tool_prune"

    @pytest.mark.asyncio
    async def test_stale_file_read_can_be_pruned(self):
        offload = AsyncMock(return_value="/archive/test.gz")
        proc = ActiveToolResultPruneProcessor(
            threshold_tokens=100,
            keep_recent_calls=1,
            on_prune_offload=offload,
        )
        large = _large_content(3000)
        messages = [HumanMessage(content="hi")]
        for i in range(3):
            tc_id = f"tc{i}"
            messages.extend(
                [
                    _make_ai_msg([{"id": tc_id, "name": "file_read_tool", "args": {}}]),
                    _make_tool_msg(
                        large if i == 0 else "small",
                        name="file_read_tool",
                        tool_call_id=tc_id,
                    ),
                ]
            )
        ctx = _build_context(messages)
        result = await proc.process(ctx)

        assert result.tokens_saved > 0
        assert isinstance(result.messages[2].content, str)
        assert "file_read_tool" in result.messages[2].content
        offload.assert_called_once()


class TestMinReclaimAndPromptCacheGates:
    @pytest.mark.asyncio
    async def test_min_reclaim_gate_skips_when_expected_savings_below_threshold(self):
        """When expected savings < min_reclaim_tokens, skip pruning to preserve prompt cache."""
        offload = AsyncMock(return_value="/archive/test.gz")
        proc = ActiveToolResultPruneProcessor(
            threshold_tokens=500,
            keep_recent_calls=1,
            min_reclaim_tokens=4096,
            on_prune_offload=offload,
        )
        # Content with ~2000 tokens (less than 4096 min_reclaim)
        medium_content = _large_content(500)
        messages = [
            HumanMessage(content="hi"),
            _make_ai_msg([{"id": "tc1", "name": "grep_tool", "args": {}}]),
            _make_tool_msg(medium_content, tool_call_id="tc1"),
            _make_ai_msg([{"id": "tc2", "name": "web_search", "args": {}}]),
            _make_tool_msg("small", name="web_search", tool_call_id="tc2"),
        ]
        ctx = _build_context(messages)
        result = await proc.process(ctx)

        # Must skip pruning: 0 tokens saved, original message content untouched
        assert result.tokens_saved == 0
        assert result.messages[2].content == medium_content
        offload.assert_not_called()

    @pytest.mark.asyncio
    async def test_min_reclaim_gate_commits_when_expected_savings_exceeds_threshold(self):
        """When aggregate expected savings >= min_reclaim_tokens, commit pruning."""
        offload = AsyncMock(return_value="/archive/test.gz")
        proc = ActiveToolResultPruneProcessor(
            threshold_tokens=500,
            keep_recent_calls=1,
            min_reclaim_tokens=4096,
            on_prune_offload=offload,
        )
        # 2 old tool messages with ~3000 tokens each (~6000 tokens total > 4096)
        large_1 = _large_content(3000)
        large_2 = _large_content(3000)
        messages = [
            HumanMessage(content="hi"),
            _make_ai_msg([{"id": "tc1", "name": "grep_tool", "args": {}}]),
            _make_tool_msg(large_1, tool_call_id="tc1"),
            _make_ai_msg([{"id": "tc2", "name": "file_read_tool", "args": {}}]),
            _make_tool_msg(large_2, name="file_read_tool", tool_call_id="tc2"),
            _make_ai_msg([{"id": "tc3", "name": "web_search", "args": {}}]),
            _make_tool_msg("small", name="web_search", tool_call_id="tc3"),
        ]
        ctx = _build_context(messages)
        result = await proc.process(ctx)

        assert result.tokens_saved > 4000
        assert offload.call_count == 2
        assert "[Tool result archived" in str(result.messages[2].content)
        assert "[Tool result archived" in str(result.messages[4].content)

    @pytest.mark.asyncio
    async def test_force_prune_bypasses_min_reclaim_gate(self):
        """force_prune=True in metadata bypasses min_reclaim_tokens (used by emergency compaction)."""
        offload = AsyncMock(return_value="/archive/test.gz")
        proc = ActiveToolResultPruneProcessor(
            threshold_tokens=500,
            keep_recent_calls=1,
            min_reclaim_tokens=4096,
            on_prune_offload=offload,
        )
        medium_content = _large_content(2000)
        messages = [
            HumanMessage(content="hi"),
            _make_ai_msg([{"id": "tc1", "name": "grep_tool", "args": {}}]),
            _make_tool_msg(medium_content, tool_call_id="tc1"),
            _make_ai_msg([{"id": "tc2", "name": "web_search", "args": {}}]),
            _make_tool_msg("small", name="web_search", tool_call_id="tc2"),
        ]
        ctx = _build_context(messages, metadata={"force_prune": True})
        result = await proc.process(ctx)

        assert result.tokens_saved > 0
        offload.assert_called_once()
        assert "[Tool result archived" in str(result.messages[2].content)

    @pytest.mark.asyncio
    async def test_force_prune_without_offload_uses_inline_emergency_placeholder(self):
        """force_prune=True with on_prune_offload=None performs inline truncation for zero-dependency recovery."""
        proc = ActiveToolResultPruneProcessor(
            threshold_tokens=500,
            keep_recent_calls=1,
            min_reclaim_tokens=4096,
            on_prune_offload=None,
        )
        large_content = _large_content(3000)
        messages = [
            HumanMessage(content="hi"),
            _make_ai_msg([{"id": "tc1", "name": "grep_tool", "args": {}}]),
            _make_tool_msg(large_content, tool_call_id="tc1"),
            _make_ai_msg([{"id": "tc2", "name": "web_search", "args": {}}]),
            _make_tool_msg("small", name="web_search", tool_call_id="tc2"),
        ]
        ctx = _build_context(messages, metadata={"force_prune": True})
        result = await proc.process(ctx)

        assert result.tokens_saved > 0
        assert "[Tool output pruned: original size" in str(result.messages[2].content)
        assert "active_prune" in str(result.messages[2].content)

    @pytest.mark.asyncio
    async def test_proactive_prune_tokens_should_process_gate(self):
        """When proactive_prune_tokens > 0, should_process returns False until total tokens exceeds threshold."""
        proc = ActiveToolResultPruneProcessor(
            threshold_tokens=500,
            proactive_prune_tokens=50000,
        )
        small_messages = [
            HumanMessage(content="hi"),
            _make_ai_msg(),
            _make_tool_msg("result"),
            _make_ai_msg(),
        ]
        ctx = _build_context(small_messages)
        # Total tokens are far below 50,000
        assert await proc.should_process(ctx) is False

        # force_prune bypasses the threshold check
        ctx_forced = _build_context(small_messages, metadata={"force_prune": True})
        assert await proc.should_process(ctx_forced) is True



class TestProcessorName:
    def test_name(self):
        proc = ActiveToolResultPruneProcessor()
        assert proc.name == "active_tool_result_prune"
