"""Tests for compress processor batching, intent propagation, and fallback."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor import (
    CompressProcessor,
    _extract_failed_tool_call_ids,
    _extract_focus_files,
    _extract_focus_modules,
    _extract_user_goal_hint,
)


class _FakeBudget:
    def __init__(
        self,
        *,
        dynamic_threshold: int,
        dynamic_min_save: int,
        remaining_ratio: float | None = 1.0,
    ) -> None:
        self._dynamic_threshold = dynamic_threshold
        self._dynamic_min_save = dynamic_min_save
        self.remaining_ratio = remaining_ratio

    def calculate_dynamic_thresholds(
        self, *, turn_count: int, estimated_remaining_turns: int = 10
    ) -> tuple[int, int]:
        _ = (turn_count, estimated_remaining_turns)
        return self._dynamic_threshold, self._dynamic_min_save

    def get_dynamic_compress_min_save(self) -> int:
        return self._dynamic_min_save


def _build_context(
    *, messages: list | None = None, metadata: dict[str, object] | None = None
) -> ProcessorContext:
    return ProcessorContext(
        messages=messages or [HumanMessage(content="Please continue")],
        user_query="Please continue",
        user_id="user-1",
        chat_id="chat-1",
        metadata=metadata or {},
    )


class TestCompressProcessorProcess:
    @pytest.mark.asyncio
    async def test_process_passes_intent_and_records_boundary_snapshot(self) -> None:
        detector = Mock()
        snapshot_callback = AsyncMock(return_value="/tmp/context-snapshot.json")
        processor = CompressProcessor(
            max_context_tokens=10000,
            compress_min_save=300,
            on_context_snapshot=snapshot_callback,
        )
        original_messages = [
            HumanMessage(content="Please fix timeout"),
            AIMessage(
                content="Call old tool",
                tool_calls=[
                    {"name": "bash", "args": {"command": "pytest old"}, "id": "call_1"}
                ],
            ),
            ToolMessage(content="Old result", tool_call_id="call_1", name="bash"),
            AIMessage(
                content="Call latest tool",
                tool_calls=[
                    {
                        "name": "bash",
                        "args": {"command": "pytest focus"},
                        "id": "call_2",
                    }
                ],
            ),
            ToolMessage(
                content="Latest full result", tool_call_id="call_2", name="bash"
            ),
            AIMessage(content="Final answer"),
        ]
        compressed_messages = [
            HumanMessage(content="Please fix timeout"),
            AIMessage(
                content="Call old tool",
                tool_calls=[
                    {"name": "bash", "args": {"command": "pytest old"}, "id": "call_1"}
                ],
            ),
            ToolMessage(
                content="COMPACTED: old result", tool_call_id="call_1", name="bash"
            ),
            AIMessage(
                content="Call latest tool",
                tool_calls=[
                    {
                        "name": "bash",
                        "args": {"command": "pytest focus"},
                        "id": "call_2",
                    }
                ],
            ),
            ToolMessage(
                content="Latest full result", tool_call_id="call_2", name="bash"
            ),
            AIMessage(content="Final answer"),
        ]
        context = _build_context(
            messages=original_messages,
            metadata={
                "compression_intent": {
                    "failed_tool_call_ids": ["call_2", "", 123],
                    "focus_files": ["src/app.py", ""],
                    "focus_modules": ["agent.context_management", None],
                    "user_goal_hint": " fix login timeout ",
                }
            },
        )

        with (
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.calculate_context_budget",
                return_value=_FakeBudget(
                    dynamic_threshold=100, dynamic_min_save=120, remaining_ratio=0.4
                ),
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.estimate_messages_tokens",
                side_effect=[1000, 5000, 700],
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.compress_messages_async",
                new=AsyncMock(return_value=(compressed_messages, 300)),
            ) as mock_compress,
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.apply_smart_fallback",
                new=AsyncMock(),
            ) as mock_fallback,
            patch(
                "myrm_agent_harness.agent.context_management.infra.cache_break_detector.get_cache_break_detector",
                return_value=detector,
            ),
        ):
            result = await processor.process(context)

        compress_kwargs = mock_compress.await_args.kwargs
        assert compress_kwargs["dynamic_min_save"] == 120
        assert compress_kwargs["failed_tool_call_ids"] == frozenset({"call_2"})
        assert compress_kwargs["focus_files"] == frozenset({"src/app.py"})
        assert compress_kwargs["focus_modules"] == frozenset(
            {"agent.context_management"}
        )
        assert compress_kwargs["user_goal_hint"] == "fix login timeout"

        snapshot_kwargs = snapshot_callback.await_args.kwargs
        assert snapshot_kwargs["messages"] is original_messages
        assert snapshot_kwargs["chat_id"] == "chat-1"
        assert snapshot_kwargs["user_id"] == "user-1"

        mock_fallback.assert_not_awaited()
        detector.notify_compaction.assert_called_once()
        assert result.tokens_saved == 300
        assert result.metadata["context_snapshot_path"] == "/tmp/context-snapshot.json"
        assert result.metadata["last_compress_boundary_index"] == 4
        assert result.metadata["compression_count"] == 1

    @pytest.mark.asyncio
    async def test_process_applies_fallback_and_tracks_low_efficiency(self) -> None:
        snapshot_callback = AsyncMock(side_effect=RuntimeError("snapshot failed"))
        processor = CompressProcessor(
            max_context_tokens=10000, on_context_snapshot=snapshot_callback
        )
        original_messages = [
            HumanMessage(content="Please continue"),
            AIMessage(
                content="Call tool",
                tool_calls=[
                    {"name": "bash", "args": {"command": "pytest"}, "id": "call_1"}
                ],
            ),
            ToolMessage(content="Large result", tool_call_id="call_1", name="bash"),
        ]
        fallback_messages = [
            HumanMessage(content="Please continue"),
            AIMessage(content="Fallback result"),
        ]
        context = _build_context(messages=original_messages)

        with (
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.calculate_context_budget",
                return_value=_FakeBudget(
                    dynamic_threshold=100, dynamic_min_save=80, remaining_ratio=0.2
                ),
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.estimate_messages_tokens",
                side_effect=[1000, 9600, 930],
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.compress_messages_async",
                new=AsyncMock(return_value=(original_messages, 50)),
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.apply_smart_fallback",
                new=AsyncMock(return_value=(fallback_messages, 20)),
            ) as mock_fallback,
            patch(
                "myrm_agent_harness.agent.context_management.infra.cache_break_detector.get_cache_break_detector",
                return_value=None,
            ),
        ):
            result = await processor.process(context)

        mock_fallback.assert_awaited_once_with(original_messages, max_tokens=9000)
        assert result.messages == fallback_messages
        assert result.tokens_saved == 70
        assert result.metadata["compression_count"] == 1
        assert "context_snapshot_path" not in result.metadata
        assert "last_compress_boundary_index" not in result.metadata

    def test_find_compress_boundary_skips_compacted_tool_messages(self) -> None:
        processor = CompressProcessor()
        messages = [
            HumanMessage(content="Query"),
            ToolMessage(content="COMPACTED: old", tool_call_id="call_1", name="bash"),
            ToolMessage(content="Latest result", tool_call_id="call_2", name="bash"),
        ]

        assert processor._find_compress_boundary(messages) == 2
        assert processor._find_compress_boundary(messages[:2]) == -1


class TestCompressionIntentExtraction:
    def test_extract_helpers_filter_invalid_values(self) -> None:
        context = _build_context(
            metadata={
                "compression_intent": {
                    "failed_tool_call_ids": ["call_1", "", None, 1],
                    "focus_files": ["src/app.py", "", None],
                    "focus_modules": ["agent.context", "", None],
                    "user_goal_hint": "  fix timeout  ",
                }
            }
        )

        assert _extract_failed_tool_call_ids(context) == frozenset({"call_1"})
        assert _extract_focus_files(context) == frozenset({"src/app.py"})
        assert _extract_focus_modules(context) == frozenset({"agent.context"})
        assert _extract_user_goal_hint(context) == "fix timeout"

    def test_extract_helpers_ignore_invalid_payload_shape(self) -> None:
        context = _build_context(metadata={"compression_intent": "invalid"})

        assert _extract_failed_tool_call_ids(context) == frozenset()
        assert _extract_focus_files(context) == frozenset()
        assert _extract_focus_modules(context) == frozenset()
        assert _extract_user_goal_hint(context) == ""

    def test_extract_helpers_missing_fields_in_valid_intent(self) -> None:
        """Intent is dict but individual fields are missing or wrong type."""
        context = _build_context(metadata={"compression_intent": {}})

        assert _extract_failed_tool_call_ids(context) == frozenset()
        assert _extract_focus_files(context) == frozenset()
        assert _extract_focus_modules(context) == frozenset()
        assert _extract_user_goal_hint(context) == ""

    def test_extract_helpers_wrong_field_types(self) -> None:
        """Intent has fields but with wrong types."""
        context = _build_context(
            metadata={
                "compression_intent": {
                    "failed_tool_call_ids": "not_a_list",
                    "focus_files": 42,
                    "focus_modules": True,
                    "user_goal_hint": 123,
                }
            }
        )

        assert _extract_failed_tool_call_ids(context) == frozenset()
        assert _extract_focus_files(context) == frozenset()
        assert _extract_focus_modules(context) == frozenset()
        assert _extract_user_goal_hint(context) == ""


class TestEcoMode:
    """Eco mode: budget pressure triggers more aggressive compression."""

    @pytest.mark.asyncio
    async def test_eco_mode_reduces_keep_recent_calls(self) -> None:
        """Eco mode reduces keep_recent_calls by 2 (min 2) during compression."""
        processor = CompressProcessor(max_context_tokens=1000, keep_recent_calls=5)
        context = _build_context(metadata={"eco_mode": True})

        captured_config = {}

        async def mock_compress(messages, *, config=None, **kw):
            captured_config["keep_recent_calls"] = (
                config.keep_recent_calls if config else None
            )
            return messages, 0

        with (
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.calculate_context_budget",
                return_value=_FakeBudget(dynamic_threshold=100, dynamic_min_save=50),
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.estimate_messages_tokens",
                return_value=200,
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.compress_messages_async",
                side_effect=mock_compress,
            ),
            patch.object(
                processor, "_should_skip_for_cache_preservation", return_value=False
            ),
        ):
            await processor.process(context)

        # keep_recent_calls should be reduced from 5 to 3 (5 - 2)
        assert captured_config["keep_recent_calls"] == 3

    @pytest.mark.asyncio
    async def test_eco_mode_off_uses_default_keep_recent(self) -> None:
        """Without eco mode, keep_recent_calls stays at configured value."""
        processor = CompressProcessor(max_context_tokens=1000, keep_recent_calls=5)
        context = _build_context(metadata={"eco_mode": False})

        captured_config = {}

        async def mock_compress(messages, *, config=None, **kw):
            captured_config["keep_recent_calls"] = (
                config.keep_recent_calls if config else None
            )
            return messages, 0

        with (
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.calculate_context_budget",
                return_value=_FakeBudget(dynamic_threshold=100, dynamic_min_save=50),
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.estimate_messages_tokens",
                return_value=200,
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.compress_messages_async",
                side_effect=mock_compress,
            ),
            patch.object(
                processor, "_should_skip_for_cache_preservation", return_value=False
            ),
        ):
            await processor.process(context)

        assert captured_config["keep_recent_calls"] == 5

    def test_eco_mode_minimum_keep_recent(self) -> None:
        """Eco mode never reduces keep_recent_calls below 2."""
        processor = CompressProcessor(max_context_tokens=1000, keep_recent_calls=2)
        assert processor._is_eco_mode(_build_context(metadata={"eco_mode": True}))
        # With keep_recent_calls=2, max(2, 2-2)=max(2,0)=2
        eco_keep = max(
            2, processor.config.keep_recent_calls - processor._ECO_KEEP_RECENT_REDUCTION
        )
        assert eco_keep == 2
