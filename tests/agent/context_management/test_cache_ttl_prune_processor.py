"""Tests for CacheTtlPruneProcessor."""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from myrm_agent_harness.agent.context_management.archive_checkpoint import (
    ArchiveSummaryService,
    reset_archive_summary_pending_state,
)
from myrm_agent_harness.agent.context_management.infra.archive_reference import (
    build_tool_result_archive_reference,
)
from myrm_agent_harness.agent.context_management.infra.schemas import (
    CacheTtlPruneConfig,
    CacheUsageFeedback,
    ContextCompressOffloadCallback,
    ContextOffloadResult,
    ToolProtectionConfig,
)
from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.processors.cache_ttl_prune_processor import (
    CacheTtlPruneProcessor,
    _find_assistant_cutoff,
    _find_first_human_index,
    _soft_trim_content,
)
from myrm_agent_harness.agent.context_management.tracking.task_metrics import (
    clear_task_metrics,
    create_task_metrics,
)


def _build_context(
    messages: list[BaseMessage] | None = None,
    metadata: dict[str, object] | None = None,
    is_resume: bool = False,
    chat_id: str | None = None,
) -> ProcessorContext:
    return ProcessorContext(
        messages=messages or [],
        user_query="test",
        is_resume=is_resume,
        chat_id=chat_id,
        metadata=metadata or {},
        merged_context={},
    )


def _make_tool_msg(content: str, name: str = "grep_tool") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id="tc_1", name=name)


def _make_large_tool_msg(size: int = 5000, name: str = "grep_tool") -> ToolMessage:
    return ToolMessage(content="x" * size, tool_call_id="tc_1", name=name)


def _successful_offload(
    paths: list[str] | None = None,
) -> ContextCompressOffloadCallback:
    async def offload(
        *,
        content: str,
        tool_name: str,
        scope_id: str | None,
    ) -> str:
        _ = content
        path = f".context/{scope_id or 'test'}/compacted/{tool_name}.txt"
        if paths is not None:
            paths.append(path)
        return path

    return offload


async def _failed_offload(
    *,
    content: str,
    tool_name: str,
    scope_id: str | None,
) -> ContextOffloadResult:
    _ = content, tool_name, scope_id
    return ContextOffloadResult.failure("quota_exceeded", "quota full")


class TestSoftTrimContent:
    """Test _soft_trim_content helper."""

    def test_small_content_returns_none(self) -> None:
        config = CacheTtlPruneConfig(soft_trim_head_chars=1500, soft_trim_tail_chars=1500)
        result = _soft_trim_content("short text", config)
        assert result is None

    def test_large_content_is_trimmed(self) -> None:
        config = CacheTtlPruneConfig(soft_trim_head_chars=100, soft_trim_tail_chars=100)
        content = "A" * 500 + "B" * 500
        result = _soft_trim_content(content, config)
        assert result is not None
        assert result.startswith("A" * 100)
        assert "B" * 100 in result
        assert "..." in result
        assert "Tool result trimmed" in result

    def test_preserves_head_and_tail(self) -> None:
        config = CacheTtlPruneConfig(soft_trim_head_chars=50, soft_trim_tail_chars=50)
        content = "HEAD_" * 20 + "MIDDLE_" * 100 + "TAIL_" * 20
        result = _soft_trim_content(content, config)
        assert result is not None
        assert result[:50] == content[:50]
        assert content[-50:] in result

    def test_json_content_uses_structure_aware_trim(self) -> None:
        config = CacheTtlPruneConfig(soft_trim_head_chars=30, soft_trim_tail_chars=30)
        content = json.dumps({"items": [{"title": f"item-{i}", "body": "x" * 200} for i in range(20)]})
        result = _soft_trim_content(content, config)
        assert result is not None
        assert '"strategy":"json_structure"' in result
        assert '"trimmed_list":true' in result
        assert "Tool result trimmed" not in result

    def test_large_json_payload_uses_fast_text_trim(self) -> None:
        config = CacheTtlPruneConfig(
            soft_trim_head_chars=30,
            soft_trim_tail_chars=30,
            large_payload_fast_guard_chars=100,
        )
        content = json.dumps({"items": [{"title": f"item-{i}", "body": "x" * 200} for i in range(20)]})

        result = _soft_trim_content(content, config)

        assert result is not None
        assert "strategy=text_head_tail" in result
        assert '"strategy":"json_structure"' not in result


class TestFindFirstHumanIndex:
    """Test _find_first_human_index helper."""

    def test_empty_messages(self) -> None:
        assert _find_first_human_index([]) is None

    def test_no_human_message(self) -> None:
        msgs = [SystemMessage(content="sys"), AIMessage(content="ai")]
        assert _find_first_human_index(msgs) is None

    def test_finds_first_human(self) -> None:
        msgs = [
            SystemMessage(content="sys"),
            AIMessage(content="ai"),
            HumanMessage(content="hello"),
            HumanMessage(content="world"),
        ]
        assert _find_first_human_index(msgs) == 2


class TestFindAssistantCutoff:
    """Test _find_assistant_cutoff helper."""

    def test_keep_zero_returns_length(self) -> None:
        msgs = [AIMessage(content="a"), AIMessage(content="b")]
        assert _find_assistant_cutoff(msgs, 0) == 2

    def test_keep_last_3(self) -> None:
        msgs = [
            HumanMessage(content="h1"),
            AIMessage(content="a1"),
            HumanMessage(content="h2"),
            AIMessage(content="a2"),
            HumanMessage(content="h3"),
            AIMessage(content="a3"),
        ]
        assert _find_assistant_cutoff(msgs, 3) == 1

    def test_not_enough_assistants_protects_all(self) -> None:
        """When fewer than keep_last assistants exist, protect all messages."""
        msgs = [HumanMessage(content="h1"), AIMessage(content="a1")]
        assert _find_assistant_cutoff(msgs, 5) == 0


class TestCacheTtlPruneProcessorName:
    """Test processor identity."""

    def test_name(self) -> None:
        processor = CacheTtlPruneProcessor()
        assert processor.name == "cache_ttl_prune"


def test_archive_reference_indexes_structured_restore_ranges() -> None:
    content = "\n".join(
        [
            "# Search Results",
            "- first item",
            "- second item",
            "| name | value |",
            "| one | 1 |",
            "```python",
            "print('hello')",
            "```",
        ]
    )

    archive_ref = build_tool_result_archive_reference(
        tool_name="search_tool",
        archive_path=".context/chat/compacted/search.txt",
        content=content,
        original_tokens=200,
        original_chars=len(content),
    )

    assert archive_ref.content_index["markdown_headings"] == [{"line": 1, "level": 1, "text": "Search Results"}]
    assert archive_ref.content_index["table_ranges"] == [{"start_line": 4, "end_line": 5}]
    assert archive_ref.content_index["code_block_ranges"] == [{"start_line": 6, "end_line": 8, "language": "python"}]


class TestShouldProcess:
    """Test should_process logic."""

    @pytest.mark.asyncio
    async def test_skip_on_resume(self) -> None:
        processor = CacheTtlPruneProcessor()
        context = _build_context(is_resume=True)
        assert await processor.should_process(context) is False

    @pytest.mark.asyncio
    async def test_skip_when_cache_not_expired(self) -> None:
        processor = CacheTtlPruneProcessor()
        context = _build_context(
            messages=[HumanMessage(content="hi"), _make_large_tool_msg(60000)],
            metadata={"last_activity_time": time.time()},
        )
        assert await processor.should_process(context) is False

    @pytest.mark.asyncio
    async def test_skip_when_ratio_below_threshold(self) -> None:
        """Small context below soft_trim_ratio should not trigger."""
        processor = CacheTtlPruneProcessor(max_context_tokens=1000000)
        context = _build_context(
            messages=[HumanMessage(content="hi"), _make_tool_msg("small")],
            metadata={"last_activity_time": time.time() - 400},
        )
        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.cache_ttl_prune_processor.get_cache_break_detector",
            return_value=None,
        ):
            assert await processor.should_process(context) is False

    @pytest.mark.asyncio
    async def test_skip_when_not_enough_prunable_chars(self) -> None:
        """Content below min_prunable_tokens should not trigger."""
        config = CacheTtlPruneConfig(min_prunable_tokens=100000)
        processor = CacheTtlPruneProcessor(config=config, max_context_tokens=50000)
        msgs = [HumanMessage(content="hi")]
        msgs.extend(_make_large_tool_msg(3000) for _ in range(5))
        context = _build_context(
            messages=msgs,
            metadata={"last_activity_time": time.time() - 400},
        )
        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.cache_ttl_prune_processor.get_cache_break_detector",
            return_value=None,
        ):
            assert await processor.should_process(context) is False

    @pytest.mark.asyncio
    async def test_triggers_when_conditions_met(self) -> None:
        """Large expired context should trigger pruning."""
        config = CacheTtlPruneConfig(min_prunable_tokens=1000, keep_last_assistant_turns=1)
        processor = CacheTtlPruneProcessor(config=config, max_context_tokens=20000)
        msgs: list[BaseMessage] = [HumanMessage(content="hi")]
        for i in range(10):
            msgs.append(AIMessage(content=f"response_{i}"))
            msgs.append(_make_large_tool_msg(10000, name=f"tool_{i}"))
        context = _build_context(
            messages=msgs,
            metadata={"last_activity_time": time.time() - 400},
        )
        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.cache_ttl_prune_processor.get_cache_break_detector",
            return_value=None,
        ):
            assert await processor.should_process(context) is True

    @pytest.mark.asyncio
    async def test_cache_feedback_keeps_hot_cache_unpruned(self) -> None:
        config = CacheTtlPruneConfig(min_prunable_tokens=100)
        processor = CacheTtlPruneProcessor(config=config, max_context_tokens=10000)
        msgs = [HumanMessage(content="hi")]
        msgs.extend(_make_large_tool_msg(10000, name=f"t_{i}") for i in range(5))
        context = _build_context(
            messages=msgs,
            metadata={
                "last_activity_time": time.time() - 10_000,
                "cache_usage_feedback": CacheUsageFeedback(
                    cache_hit_rate=0.8,
                    cached_tokens=8_000,
                    input_tokens=10_000,
                    calls=3,
                ),
            },
        )

        assert await processor.should_process(context) is False

    @pytest.mark.asyncio
    async def test_cache_feedback_triggers_cold_cache_before_ttl(self) -> None:
        config = CacheTtlPruneConfig(ttl_seconds=10_000, min_prunable_tokens=100, keep_last_assistant_turns=0)
        processor = CacheTtlPruneProcessor(config=config, max_context_tokens=1000)
        msgs = [HumanMessage(content="hi")]
        msgs.extend(_make_large_tool_msg(10000, name=f"t_{i}") for i in range(5))
        context = _build_context(
            messages=msgs,
            metadata={
                "last_activity_time": time.time(),
                "cache_usage_feedback": CacheUsageFeedback(
                    cache_hit_rate=0.0,
                    cached_tokens=0,
                    input_tokens=12_000,
                    calls=3,
                ),
            },
        )

        assert await processor.should_process(context) is True


class TestProcess:
    """Test process execution."""

    @pytest.mark.asyncio
    async def test_soft_trim_applied(self) -> None:
        """Tool results are soft-trimmed when ratio is between soft and hard thresholds."""
        config = CacheTtlPruneConfig(
            soft_trim_ratio=0.01,
            hard_clear_ratio=0.9,
            min_prunable_tokens=100,
            soft_trim_head_chars=50,
            soft_trim_tail_chars=50,
            keep_last_assistant_turns=0,
        )
        processor = CacheTtlPruneProcessor(config=config, max_context_tokens=5000)
        large_content = "X" * 5000
        msgs = [HumanMessage(content="hi"), _make_tool_msg(large_content)]
        context = _build_context(
            messages=msgs,
            metadata={"last_activity_time": time.time() - 400},
        )
        result = await processor.process(context)
        trimmed = result.messages[1].content
        assert "..." in trimmed
        assert "Tool result trimmed" in trimmed
        assert result.tokens_saved > 0

    @pytest.mark.asyncio
    async def test_soft_trim_replaces_message_without_mutating_original(self) -> None:
        config = CacheTtlPruneConfig(
            soft_trim_ratio=0.01,
            hard_clear_ratio=0.9,
            min_prunable_tokens=100,
            soft_trim_head_chars=50,
            soft_trim_tail_chars=50,
            keep_last_assistant_turns=0,
        )
        processor = CacheTtlPruneProcessor(config=config, max_context_tokens=5000)
        original_content = "X" * 5000
        tool_msg = _make_tool_msg(original_content)
        context = _build_context(
            messages=[HumanMessage(content="hi"), tool_msg],
            metadata={"last_activity_time": time.time() - 400},
        )

        result = await processor.process(context)

        assert tool_msg.content == original_content
        assert result.messages[1] is not tool_msg
        assert result.messages[1].content != original_content

    @pytest.mark.asyncio
    async def test_large_payload_fast_guard_avoids_exact_tokenization(self) -> None:
        config = CacheTtlPruneConfig(
            soft_trim_ratio=0.01,
            hard_clear_ratio=9.0,
            min_prunable_tokens=1,
            soft_trim_head_chars=50,
            soft_trim_tail_chars=50,
            keep_last_assistant_turns=0,
            large_payload_fast_guard_chars=100,
        )
        processor = CacheTtlPruneProcessor(config=config, max_context_tokens=128_000)
        large_content = "X" * 250_000
        context = _build_context(
            messages=[HumanMessage(content="hi"), _make_tool_msg(large_content)],
            metadata={"last_activity_time": time.time() - 400},
        )

        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.cache_ttl_prune_processor.estimate_content_tokens",
            side_effect=AssertionError("exact tokenization should not run for large payload"),
        ):
            result = await processor.process(context)

        assert result.messages[1].content != large_content
        assert "Tool result trimmed" in result.messages[1].content
        assert result.tokens_saved > 0

    @pytest.mark.asyncio
    async def test_hard_archive_applied(self) -> None:
        """Tool results are archived when ratio exceeds hard_clear_ratio."""
        config = CacheTtlPruneConfig(
            soft_trim_ratio=0.01,
            hard_clear_ratio=0.02,
            min_prunable_tokens=100,
            keep_last_assistant_turns=0,
        )
        offloaded_paths: list[str] = []
        processor = CacheTtlPruneProcessor(
            config=config,
            max_context_tokens=10000,
            on_prune_offload=_successful_offload(offloaded_paths),
        )
        msgs = [HumanMessage(content="hi")]
        msgs.extend(_make_large_tool_msg(3000, name=f"t_{i}") for i in range(5))
        context = _build_context(
            messages=msgs,
            metadata={"last_activity_time": time.time() - 400},
            chat_id="chat_1",
        )
        result = await processor.process(context)
        archived_count = sum(
            1
            for m in result.messages
            if isinstance(m, ToolMessage) and "result archived" in m.content and "archived_path" in m.content
        )
        assert archived_count > 0
        assert offloaded_paths
        assert result.tokens_saved > 0
        archived_msg = next(m for m in result.messages if isinstance(m, ToolMessage) and "result archived" in m.content)
        assert archived_msg.name in archived_msg.content
        assert "file_read_tool" in archived_msg.content
        assert "archive_ref" in archived_msg.content
        assert "restore_tool" in archived_msg.content
        assert "restore_args" in archived_msg.content
        assert "content_sha256" in archived_msg.content
        assert "content_index" in archived_msg.content
        assert "chunk_ranges" in archived_msg.content
        assert '"session_id":"chat_1"' in archived_msg.content

    @pytest.mark.asyncio
    async def test_hard_archive_records_structured_metrics(self) -> None:
        config = CacheTtlPruneConfig(
            soft_trim_ratio=0.01,
            hard_clear_ratio=0.02,
            min_prunable_tokens=100,
            keep_last_assistant_turns=0,
        )
        chat_id = "chat_cache_ttl_metrics"
        create_task_metrics(chat_id)
        try:
            processor = CacheTtlPruneProcessor(
                config=config,
                max_context_tokens=1000,
                on_prune_offload=_successful_offload(),
            )
            context = _build_context(
                messages=[HumanMessage(content="hi"), _make_large_tool_msg(5000)],
                metadata={"last_activity_time": time.time() - 400},
                chat_id=chat_id,
            )

            await processor.process(context)

            metrics = create_task_metrics(chat_id)
            exported = metrics.to_dict()
            assert exported["archive_count"] > 0
            assert exported["archived_original_tokens"] > 0
            events = exported["compression_events"]
            assert isinstance(events, list)
            assert events[0]["archive_count"] > 0
            assert events[0]["backoff_applied"] is False
            assert events[0]["effective_soft_trim_ratio"] == 0.01
            assert events[0]["effective_hard_clear_ratio"] == 0.02
            assert events[0]["effective_min_prunable_tokens"] == 100
        finally:
            clear_task_metrics(chat_id)

    @pytest.mark.asyncio
    async def test_restore_cost_ratio_backoff_raises_prune_thresholds(self) -> None:
        config = CacheTtlPruneConfig(
            soft_trim_ratio=0.01,
            hard_clear_ratio=0.02,
            min_prunable_tokens=100,
            keep_last_assistant_turns=0,
            roi_soft_trim_ratio_bump=0.1,
            roi_backoff_min_samples=1,
            roi_backoff_recovery_samples=1,
        )
        chat_id = "chat_restore_cost_backoff"
        clear_task_metrics(chat_id)
        metrics = create_task_metrics(chat_id)
        metrics.record_compression(
            tokens_saved=1000,
            compression_type="cache_ttl_prune",
            archive_count=1,
            original_tokens=4000,
        )
        metrics.record_archive_restore_result(
            archive_path=".context/chat_restore_cost_backoff/compacted/tool.txt",
            restore_arg=".context/chat_restore_cost_backoff/compacted/tool.txt:1-20",
            start_line=1,
            end_line=20,
            restored_line_count=20,
            estimated_tokens=700,
            restored_bytes=2048,
        )
        try:
            processor = CacheTtlPruneProcessor(
                config=config,
                max_context_tokens=1000,
                on_prune_offload=_successful_offload(),
            )
            context = _build_context(
                messages=[HumanMessage(content="hi"), _make_large_tool_msg(5000)],
                metadata={"last_activity_time": time.time() - 400},
                chat_id=chat_id,
            )

            await processor.process(context)

            exported = metrics.to_dict()
            events = exported["compression_events"]
            assert isinstance(events, list)
            latest = events[-1]
            assert latest["backoff_applied"] is True
            assert latest["backoff_reasons"] == [
                "high_restore_cost_ratio",
                "low_restore_roi_ratio",
            ]
            assert latest["effective_soft_trim_ratio"] == pytest.approx(0.11)
            assert latest["effective_hard_clear_ratio"] == pytest.approx(0.12)
            assert latest["effective_min_prunable_tokens"] == 200
            assert latest["backoff_sample_count"] == 1
            assert latest["backoff_bad_signal_count"] == 2
            assert latest["backoff_recovery_sample_count"] == 0
            assert exported["pruning_backoff_applied"] is True
            assert exported["pruning_backoff_reasons"] == {
                "high_restore_cost_ratio": 1,
                "low_restore_roi_ratio": 1,
            }
        finally:
            clear_task_metrics(chat_id)

    @pytest.mark.asyncio
    async def test_restore_cost_backoff_waits_for_minimum_samples(self) -> None:
        config = CacheTtlPruneConfig(
            soft_trim_ratio=0.01,
            hard_clear_ratio=0.02,
            min_prunable_tokens=100,
            keep_last_assistant_turns=0,
            roi_soft_trim_ratio_bump=0.1,
        )
        chat_id = "chat_restore_cost_min_samples"
        clear_task_metrics(chat_id)
        metrics = create_task_metrics(chat_id)
        metrics.record_compression(
            tokens_saved=1000,
            compression_type="cache_ttl_prune",
            archive_count=1,
            original_tokens=4000,
        )
        metrics.record_archive_restore_result(
            archive_path=".context/chat_restore_cost_min_samples/compacted/tool.txt",
            restore_arg=".context/chat_restore_cost_min_samples/compacted/tool.txt:1-20",
            start_line=1,
            end_line=20,
            restored_line_count=20,
            estimated_tokens=700,
            restored_bytes=2048,
        )
        try:
            processor = CacheTtlPruneProcessor(
                config=config,
                max_context_tokens=1000,
                on_prune_offload=_successful_offload(),
            )
            context = _build_context(
                messages=[HumanMessage(content="hi"), _make_large_tool_msg(5000)],
                metadata={"last_activity_time": time.time() - 400},
                chat_id=chat_id,
            )

            await processor.process(context)

            latest = metrics.to_dict()["compression_events"][-1]
            assert latest["backoff_applied"] is False
            assert latest["backoff_reasons"] == []
            assert latest["backoff_sample_count"] == 1
            assert latest["effective_soft_trim_ratio"] == pytest.approx(0.01)
            assert latest["effective_hard_clear_ratio"] == pytest.approx(0.02)
            assert latest["effective_min_prunable_tokens"] == 100
        finally:
            clear_task_metrics(chat_id)

    def test_backoff_recovery_requires_healthy_hysteresis_samples(self) -> None:
        config = CacheTtlPruneConfig(
            soft_trim_ratio=0.01,
            hard_clear_ratio=0.02,
            min_prunable_tokens=100,
            roi_backoff_window_size=3,
            roi_backoff_min_samples=1,
            roi_backoff_recovery_samples=3,
        )
        chat_id = "chat_backoff_recovery"
        clear_task_metrics(chat_id)
        metrics = create_task_metrics(chat_id)
        try:
            metrics.record_compression(
                tokens_saved=1000,
                compression_type="cache_ttl_prune",
                archive_count=1,
                backoff_applied=True,
                backoff_reasons=["high_restore_cost_ratio"],
            )
            processor = CacheTtlPruneProcessor(config=config)
            context = _build_context(chat_id=chat_id)

            recovering_policy = processor._effective_policy(context)

            assert recovering_policy.backoff_applied is True
            assert recovering_policy.backoff_reasons == ("recovery_hysteresis",)
            assert recovering_policy.backoff_sample_count == 1
            assert recovering_policy.backoff_recovery_sample_count == 1

            metrics.record_compression(tokens_saved=1000, compression_type="cache_ttl_prune", archive_count=1)
            metrics.record_compression(tokens_saved=1000, compression_type="cache_ttl_prune", archive_count=1)

            recovered_policy = processor._effective_policy(context)

            assert recovered_policy.backoff_applied is False
            assert recovered_policy.backoff_reasons == ()
            assert recovered_policy.backoff_sample_count == 3
            assert recovered_policy.backoff_recovery_sample_count == 3
        finally:
            clear_task_metrics(chat_id)

    @pytest.mark.asyncio
    async def test_hard_archive_reuses_successful_offload_for_retry(self) -> None:
        """Retrying the same archive candidate should keep one stable offload path."""
        config = CacheTtlPruneConfig(
            soft_trim_ratio=0.01,
            hard_clear_ratio=0.02,
            min_prunable_tokens=100,
            keep_last_assistant_turns=0,
        )
        call_count = 0

        async def offload(
            *,
            content: str,
            tool_name: str,
            scope_id: str | None,
        ) -> str:
            nonlocal call_count
            _ = content
            call_count += 1
            return f".context/{scope_id or 'test'}/compacted/{tool_name}-{call_count}.txt"

        processor = CacheTtlPruneProcessor(
            config=config,
            max_context_tokens=10000,
            on_prune_offload=offload,
        )
        content = "Z" * 5000

        first = await processor.process(
            _build_context(
                messages=[HumanMessage(content="hi"), _make_tool_msg(content)],
                metadata={"last_activity_time": time.time() - 400},
                chat_id="chat_retry_archive",
            )
        )
        second = await processor.process(
            _build_context(
                messages=[HumanMessage(content="hi"), _make_tool_msg(content)],
                metadata={"last_activity_time": time.time() - 400},
                chat_id="chat_retry_archive",
            )
        )

        assert call_count == 1
        assert first.messages[1].content == second.messages[1].content
        assert "grep_tool-1.txt" in str(second.messages[1].content)

    @pytest.mark.asyncio
    async def test_hard_archive_does_not_cache_failed_offload(self) -> None:
        """A transient offload failure must not poison later retry attempts."""
        config = CacheTtlPruneConfig(
            soft_trim_ratio=0.01,
            hard_clear_ratio=0.02,
            min_prunable_tokens=100,
            soft_trim_head_chars=50,
            soft_trim_tail_chars=50,
            keep_last_assistant_turns=0,
        )
        call_count = 0

        async def flaky_offload(
            *,
            content: str,
            tool_name: str,
            scope_id: str | None,
        ) -> ContextOffloadResult:
            nonlocal call_count
            _ = content
            call_count += 1
            if call_count == 1:
                return ContextOffloadResult.failure("temporary_failure", "try again")
            return ContextOffloadResult.success(f".context/{scope_id or 'test'}/compacted/{tool_name}.txt")

        processor = CacheTtlPruneProcessor(
            config=config,
            max_context_tokens=10000,
            on_prune_offload=flaky_offload,
        )
        content = "A" * 2500 + "B" * 2500

        first = await processor.process(
            _build_context(
                messages=[HumanMessage(content="hi"), _make_tool_msg(content)],
                metadata={"last_activity_time": time.time() - 400},
                chat_id="chat_retry_after_failure",
            )
        )
        second = await processor.process(
            _build_context(
                messages=[HumanMessage(content="hi"), _make_tool_msg(content)],
                metadata={"last_activity_time": time.time() - 400},
                chat_id="chat_retry_after_failure",
            )
        )

        assert call_count == 2
        assert "Tool result trimmed" in str(first.messages[1].content)
        assert "result archived" in str(second.messages[1].content)

    @pytest.mark.asyncio
    async def test_hard_archive_does_not_reuse_offload_without_chat_id(self) -> None:
        """Anonymous contexts must not share archive paths through the idempotency cache."""
        config = CacheTtlPruneConfig(
            soft_trim_ratio=0.01,
            hard_clear_ratio=0.02,
            min_prunable_tokens=100,
            keep_last_assistant_turns=0,
        )
        call_count = 0

        async def offload(
            *,
            content: str,
            tool_name: str,
            scope_id: str | None,
        ) -> str:
            nonlocal call_count
            _ = content, scope_id
            call_count += 1
            return f".context/anonymous/compacted/{tool_name}-{call_count}.txt"

        processor = CacheTtlPruneProcessor(
            config=config,
            max_context_tokens=10000,
            on_prune_offload=offload,
        )
        content = "Z" * 5000

        await processor.process(
            _build_context(
                messages=[HumanMessage(content="hi"), _make_tool_msg(content)],
                metadata={"last_activity_time": time.time() - 400},
            )
        )
        second = await processor.process(
            _build_context(
                messages=[HumanMessage(content="hi"), _make_tool_msg(content)],
                metadata={"last_activity_time": time.time() - 400},
            )
        )

        assert call_count == 2
        assert "grep_tool-2.txt" in str(second.messages[1].content)

    @pytest.mark.asyncio
    async def test_archive_pass_budget_defers_extra_archives(self) -> None:
        config = CacheTtlPruneConfig(
            soft_trim_ratio=0.01,
            hard_clear_ratio=0.02,
            min_prunable_tokens=100,
            keep_last_assistant_turns=0,
            max_archives_per_pass=1,
            max_prune_wall_ms=0,
        )
        chat_id = "chat_cache_ttl_budget"
        metrics = create_task_metrics(chat_id)
        try:
            processor = CacheTtlPruneProcessor(
                config=config,
                max_context_tokens=10000,
                on_prune_offload=_successful_offload(),
            )
            context = _build_context(
                messages=[
                    HumanMessage(content="hi"),
                    _make_large_tool_msg(5000, name="tool_1"),
                    _make_large_tool_msg(5000, name="tool_2"),
                ],
                metadata={"last_activity_time": time.time() - 400},
                chat_id=chat_id,
            )

            result = await processor.process(context)

            archived_count = sum(
                1
                for message in result.messages
                if isinstance(message, ToolMessage) and "result archived" in message.content
            )
            assert archived_count == 1
            exported = metrics.to_dict()
            assert exported["archive_count"] == 1
            assert exported["prune_deferred_count"] == 0
            assert exported["prune_deferred_reasons"] == {}
            assert exported["archive_deferred_count"] == 1
            assert exported["archive_deferred_reasons"] == {"archive_count_budget": 1}
            assert exported["archive_deferred_soft_trimmed_count"] == 1
            assert exported["archive_deferred_soft_trimmed_reasons"] == {"archive_count_budget": 1}
        finally:
            clear_task_metrics(chat_id)

    @pytest.mark.asyncio
    async def test_soft_only_tool_is_not_archived(self) -> None:
        config = CacheTtlPruneConfig(
            soft_trim_ratio=0.01,
            hard_clear_ratio=0.02,
            min_prunable_tokens=100,
            soft_trim_head_chars=50,
            soft_trim_tail_chars=50,
            keep_last_assistant_turns=0,
        )
        protection = ToolProtectionConfig(
            business_protected=set(),
            soft_only_tools={"recall_tool"},
        )
        processor = CacheTtlPruneProcessor(
            config=config,
            protection_config=protection,
            max_context_tokens=10000,
            on_prune_offload=_successful_offload(),
        )
        context = _build_context(
            messages=[
                HumanMessage(content="hi"),
                _make_large_tool_msg(5000, name="recall_tool"),
            ],
            metadata={"last_activity_time": time.time() - 400},
            chat_id="chat_1",
        )

        result = await processor.process(context)

        content = result.messages[1].content
        assert isinstance(content, str)
        assert "result archived" not in content
        assert "Tool result trimmed" in content

    @pytest.mark.asyncio
    async def test_hard_archive_falls_back_to_soft_trim_when_offload_fails(
        self,
    ) -> None:
        """Hard pruning must preserve information when offload is unavailable."""
        config = CacheTtlPruneConfig(
            soft_trim_ratio=0.01,
            hard_clear_ratio=0.02,
            min_prunable_tokens=100,
            soft_trim_head_chars=50,
            soft_trim_tail_chars=50,
            keep_last_assistant_turns=0,
        )
        processor = CacheTtlPruneProcessor(
            config=config,
            max_context_tokens=10000,
            on_prune_offload=_failed_offload,
        )
        content = "A" * 2500 + "B" * 2500
        chat_id = "chat_failed_cache_ttl_offload"
        metrics = create_task_metrics(chat_id)
        context = _build_context(
            messages=[HumanMessage(content="hi"), _make_tool_msg(content)],
            metadata={"last_activity_time": time.time() - 400},
            chat_id=chat_id,
        )

        try:
            result = await processor.process(context)

            pruned_content = result.messages[1].content
            assert isinstance(pruned_content, str)
            assert "result archived" not in pruned_content
            assert "Tool result trimmed" in pruned_content
            assert pruned_content.startswith("A" * 50)
            assert "B" * 50 in pruned_content
            exported = metrics.to_dict()
            events = exported["compression_events"]
            assert isinstance(events, list)
            assert events[0]["offload_failure_kinds"] == {"quota_exceeded": 1}
            assert exported["offload_failure_kinds"] == {"quota_exceeded": 1}
        finally:
            clear_task_metrics(chat_id)

    @pytest.mark.asyncio
    async def test_protected_tools_not_pruned(self) -> None:
        """Protected tools should never be pruned."""
        config = CacheTtlPruneConfig(
            soft_trim_ratio=0.01,
            hard_clear_ratio=0.02,
            min_prunable_tokens=100,
            keep_last_assistant_turns=0,
        )
        protection = ToolProtectionConfig(business_protected={"important_tool"})
        processor = CacheTtlPruneProcessor(config=config, protection_config=protection, max_context_tokens=10000)
        protected_msg = ToolMessage(content="X" * 5000, tool_call_id="tc_p", name="important_tool")
        unprotected_msg = ToolMessage(content="Y" * 5000, tool_call_id="tc_u", name="grep_tool")
        msgs = [HumanMessage(content="hi"), protected_msg, unprotected_msg]
        context = _build_context(
            messages=msgs,
            metadata={"last_activity_time": time.time() - 400},
        )
        result = await processor.process(context)
        assert result.messages[1].content == "X" * 5000
        assert result.messages[2].content != "Y" * 5000

    @pytest.mark.asyncio
    async def test_keep_last_assistant_turns(self) -> None:
        """Messages at or after the cutoff assistant index are protected."""
        config = CacheTtlPruneConfig(
            soft_trim_ratio=0.01,
            hard_clear_ratio=0.02,
            min_prunable_tokens=100,
            keep_last_assistant_turns=2,
            max_prune_wall_ms=0,
        )
        processor = CacheTtlPruneProcessor(config=config, max_context_tokens=10000)
        old_tool = ToolMessage(content="O" * 5000, tool_call_id="tc_old", name="old_tool")
        mid_tool = ToolMessage(content="M" * 5000, tool_call_id="tc_mid", name="mid_tool")
        new_tool = ToolMessage(content="N" * 5000, tool_call_id="tc_new", name="new_tool")
        msgs = [
            HumanMessage(content="hi"),
            old_tool,
            AIMessage(content="old response"),
            HumanMessage(content="q2"),
            mid_tool,
            AIMessage(content="mid response"),  # 2nd-from-last AI → cutoff here
            HumanMessage(content="q3"),
            new_tool,
            AIMessage(content="new response"),  # last AI
        ]
        context = _build_context(
            messages=msgs,
            metadata={"last_activity_time": time.time() - 400},
        )
        result = await processor.process(context)
        # old_tool (index 1) before cutoff → pruned
        assert result.messages[1].content != "O" * 5000
        # mid_tool (index 4) before cutoff (cutoff=5) → pruned
        assert result.messages[4].content != "M" * 5000
        # new_tool (index 7) after cutoff → protected
        assert result.messages[7].content == "N" * 5000

    @pytest.mark.asyncio
    async def test_first_human_protection(self) -> None:
        """Messages before first HumanMessage are never pruned."""
        config = CacheTtlPruneConfig(
            soft_trim_ratio=0.01,
            hard_clear_ratio=0.02,
            min_prunable_tokens=100,
            keep_last_assistant_turns=0,
        )
        processor = CacheTtlPruneProcessor(config=config, max_context_tokens=10000)
        init_tool = ToolMessage(content="I" * 5000, tool_call_id="tc_init", name="init_tool")
        post_tool = ToolMessage(content="P" * 5000, tool_call_id="tc_post", name="post_tool")
        msgs = [
            SystemMessage(content="system"),
            init_tool,
            HumanMessage(content="hi"),
            post_tool,
        ]
        context = _build_context(
            messages=msgs,
            metadata={"last_activity_time": time.time() - 400},
        )
        result = await processor.process(context)
        assert result.messages[1].content == "I" * 5000
        assert result.messages[3].content != "P" * 5000

    @pytest.mark.asyncio
    async def test_skip_on_hitl_session(self) -> None:
        """Should skip when HITL session is active."""
        processor = CacheTtlPruneProcessor()
        context = _build_context(
            messages=[HumanMessage(content="hi")],
            metadata={"last_activity_time": time.time() - 400},
        )
        context.merged_context = {"hitl_session_active": True}
        assert await processor.should_process(context) is False

    @pytest.mark.asyncio
    async def test_emergency_prune_can_run_during_hitl_near_context_limit(self) -> None:
        config = CacheTtlPruneConfig(
            ttl_seconds=10_000,
            soft_trim_ratio=0.01,
            hard_clear_ratio=0.9,
            min_prunable_tokens=100,
            keep_last_assistant_turns=0,
            emergency_prune_ratio=0.05,
        )
        processor = CacheTtlPruneProcessor(config=config, max_context_tokens=10_000)
        context = _build_context(
            messages=[
                HumanMessage(content="hi"),
                _make_large_tool_msg(8_000, name="large_tool"),
            ],
            metadata={"last_activity_time": time.time()},
        )
        context.merged_context = {"hitl_session_active": True}

        assert await processor.should_process(context) is True
        result = await processor.process(context)
        assert result.messages[1].content != "x" * 8_000


class TestCacheExpiryDetection:
    """Test cache expiry detection logic."""

    @pytest.mark.asyncio
    async def test_uses_cache_break_detector(self) -> None:
        """Should use CacheBreakDetector if available."""
        config = CacheTtlPruneConfig(ttl_seconds=100, min_prunable_tokens=100)
        processor = CacheTtlPruneProcessor(config=config, max_context_tokens=10000)

        from myrm_agent_harness.agent.context_management.infra.cache_break_detector import (
            CacheBreakDetector,
        )

        mock_detector = CacheBreakDetector()
        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.cache_ttl_prune_processor.get_cache_break_detector",
            return_value=mock_detector,
        ):
            msgs = [HumanMessage(content="hi")]
            msgs.extend(_make_large_tool_msg(10000, name=f"t_{i}") for i in range(5))
            context = _build_context(messages=msgs)
            assert await processor.should_process(context) is False

    @pytest.mark.asyncio
    async def test_fallback_to_last_activity_time(self) -> None:
        """Should fall back to metadata last_activity_time when detector is None."""
        config = CacheTtlPruneConfig(ttl_seconds=100, min_prunable_tokens=100, keep_last_assistant_turns=1)
        processor = CacheTtlPruneProcessor(config=config, max_context_tokens=10000)

        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.cache_ttl_prune_processor.get_cache_break_detector",
            return_value=None,
        ):
            msgs: list[BaseMessage] = [HumanMessage(content="hi")]
            for i in range(5):
                msgs.append(AIMessage(content=f"resp_{i}"))
                msgs.append(_make_large_tool_msg(10000, name=f"t_{i}"))
            context = _build_context(
                messages=msgs,
                metadata={"last_activity_time": time.time() - 200},
            )
            assert await processor.should_process(context) is True


class TestArchiveSummaryCheckpoint:
    def test_processor_without_service_has_no_archive_summary(self) -> None:
        processor = CacheTtlPruneProcessor()
        assert processor._archive_summary_service is None

    def test_summary_service_respects_disabled_flag(self) -> None:
        chat_id = "summary-disabled"
        clear_task_metrics(chat_id)
        metrics = create_task_metrics(chat_id)
        config = CacheTtlPruneConfig(archive_summary_enabled=False)
        service = ArchiveSummaryService(config=config, store=AsyncMock())
        mock_llm = AsyncMock()

        service.dispatch(
            tool_name="grep_tool",
            content="x" * 20_000,
            archive_path=".context/summary-disabled/compacted/result.txt",
            chat_id=chat_id,
            summarizer_llm=mock_llm,
        )

        assert metrics.archive_summary_queued_count == 0
        assert metrics.archive_summary_skipped_count == 1
        assert metrics.archive_summary_skipped_reasons == {"disabled": 1}

    @pytest.mark.asyncio
    async def test_summary_service_respects_queue_budget(self) -> None:
        chat_id = "summary-queued"
        clear_task_metrics(chat_id)
        metrics = create_task_metrics(chat_id)
        config = CacheTtlPruneConfig(
            archive_summary_enabled=True,
            archive_summary_min_tokens=1,
            archive_summary_max_queue_size=0,
        )
        service = ArchiveSummaryService(config=config, store=AsyncMock())

        service.dispatch(
            tool_name="grep_tool",
            content="x" * 100,
            archive_path=".context/summary-queued/compacted/result.txt",
            chat_id=chat_id,
            summarizer_llm=AsyncMock(),
        )

        assert metrics.archive_summary_queued_count == 0
        assert metrics.archive_summary_skipped_count == 1
        assert metrics.archive_summary_skipped_reasons == {"queue_full": 1}

    @pytest.mark.asyncio
    async def test_summary_service_success_path(self) -> None:
        chat_id = "summary-success"
        clear_task_metrics(chat_id)
        metrics = create_task_metrics(chat_id)
        config = CacheTtlPruneConfig(
            archive_summary_enabled=True,
            archive_summary_min_tokens=1,
            archive_summary_max_queue_size=10,
        )
        mock_store = AsyncMock()
        mock_store.store_checkpoint.return_value = MagicMock(memory_id="mem-1")
        service = ArchiveSummaryService(config=config, store=mock_store)

        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "This is a summary"
        mock_llm.ainvoke.return_value = mock_response

        reset_archive_summary_pending_state()

        service.dispatch(
            tool_name="grep_tool",
            content="x" * 100,
            archive_path=".context/summary-success/compacted/result.txt",
            chat_id=chat_id,
            summarizer_llm=mock_llm,
        )

        assert metrics.archive_summary_queued_count == 1
        await asyncio.sleep(0.1)
        assert metrics.archive_summary_succeeded_count == 1
        mock_store.store_checkpoint.assert_awaited_once()
