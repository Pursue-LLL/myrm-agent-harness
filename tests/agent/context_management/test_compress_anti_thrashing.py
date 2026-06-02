"""Tests for Anti-Thrashing protection in CompressProcessor.

Verifies that:
1. streak < 2 allows compression normally
2. streak >= 2 skips compression when below 90% safety net
3. streak >= 2 forces compression when at/above 90% safety net
4. process() correctly updates streak in TaskMetrics based on savings_pct
5. streak persists across rounds via TaskMetrics (not reset per-round metadata)
"""

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import HumanMessage

from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor import (
    CompressProcessor,
)
from myrm_agent_harness.agent.context_management.tracking.task_metrics import (
    clear_task_metrics,
    create_task_metrics,
)


class _FakeBudget:
    def __init__(
        self, *, dynamic_threshold: int, dynamic_min_save: int = 500,
        remaining_ratio: float | None = 1.0,
    ) -> None:
        self._dynamic_threshold = dynamic_threshold
        self._dynamic_min_save = dynamic_min_save
        self.remaining_ratio = remaining_ratio

    def calculate_dynamic_thresholds(
        self, *, turn_count: int, estimated_remaining_turns: int = 10
    ) -> tuple[int, int]:
        return self._dynamic_threshold, self._dynamic_min_save

    def get_dynamic_compress_min_save(self) -> int:
        return self._dynamic_min_save


CHAT_ID = "test-anti-thrashing-chat"


def _build_context(
    *, messages: list | None = None, metadata: dict | None = None
) -> ProcessorContext:
    return ProcessorContext(
        messages=messages or [HumanMessage(content="test")],
        user_query="test",
        user_id="user-1",
        chat_id=CHAT_ID,
        metadata=metadata or {},
    )


@pytest.fixture(autouse=True)
def _cleanup_metrics():
    """Ensure metrics are fresh for each test."""
    clear_task_metrics(CHAT_ID)
    yield
    clear_task_metrics(CHAT_ID)


class TestAntiThrashingShouldProcess:
    """Tests for anti-thrashing logic in should_process()."""

    @pytest.mark.asyncio
    async def test_streak_zero_allows_compression(self) -> None:
        """streak=0: compression proceeds normally."""
        processor = CompressProcessor(max_context_tokens=100000)
        metrics = create_task_metrics(CHAT_ID)
        metrics.compression_ineffective_streak = 0
        context = _build_context()

        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.calculate_context_budget",
            return_value=_FakeBudget(dynamic_threshold=50000),
        ), patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.estimate_messages_tokens",
            return_value=60000,
        ):
            result = await processor.should_process(context)

        assert result is True

    @pytest.mark.asyncio
    async def test_streak_one_allows_compression(self) -> None:
        """streak=1: still below limit, compression proceeds."""
        processor = CompressProcessor(max_context_tokens=100000)
        metrics = create_task_metrics(CHAT_ID)
        metrics.compression_ineffective_streak = 1
        context = _build_context()

        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.calculate_context_budget",
            return_value=_FakeBudget(dynamic_threshold=50000),
        ), patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.estimate_messages_tokens",
            return_value=60000,
        ):
            result = await processor.should_process(context)

        assert result is True

    @pytest.mark.asyncio
    async def test_streak_two_skips_below_safety_net(self) -> None:
        """streak=2, tokens < 90%: compression is skipped."""
        processor = CompressProcessor(max_context_tokens=100000)
        metrics = create_task_metrics(CHAT_ID)
        metrics.compression_ineffective_streak = 2
        context = _build_context()

        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.calculate_context_budget",
            return_value=_FakeBudget(dynamic_threshold=50000),
        ), patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.estimate_messages_tokens",
            return_value=80000,
        ):
            result = await processor.should_process(context)

        assert result is False

    @pytest.mark.asyncio
    async def test_streak_two_forces_at_safety_net(self) -> None:
        """streak=2, tokens >= 90%: safety net overrides anti-thrashing."""
        processor = CompressProcessor(max_context_tokens=100000)
        metrics = create_task_metrics(CHAT_ID)
        metrics.compression_ineffective_streak = 2
        context = _build_context()

        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.calculate_context_budget",
            return_value=_FakeBudget(dynamic_threshold=50000),
        ), patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.estimate_messages_tokens",
            return_value=91000,
        ):
            result = await processor.should_process(context)

        assert result is True

    @pytest.mark.asyncio
    async def test_streak_high_still_forces_at_safety_net(self) -> None:
        """streak=5 (high), tokens >= 90%: safety net always works."""
        processor = CompressProcessor(max_context_tokens=100000)
        metrics = create_task_metrics(CHAT_ID)
        metrics.compression_ineffective_streak = 5
        context = _build_context()

        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.calculate_context_budget",
            return_value=_FakeBudget(dynamic_threshold=50000),
        ), patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.estimate_messages_tokens",
            return_value=95000,
        ):
            result = await processor.should_process(context)

        assert result is True

    @pytest.mark.asyncio
    async def test_no_chat_id_defaults_to_zero_streak(self) -> None:
        """Without chat_id, streak defaults to 0 and compression proceeds."""
        processor = CompressProcessor(max_context_tokens=100000)
        context = ProcessorContext(
            messages=[HumanMessage(content="test")],
            user_query="test",
            chat_id=None,
            metadata={},
        )

        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.calculate_context_budget",
            return_value=_FakeBudget(dynamic_threshold=50000),
        ), patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.estimate_messages_tokens",
            return_value=60000,
        ):
            result = await processor.should_process(context)

        assert result is True


class TestAntiThrashingStreakUpdate:
    """Tests for streak update logic in process()."""

    @pytest.mark.asyncio
    async def test_effective_compression_resets_streak(self) -> None:
        """savings >= 10% resets streak to 0."""
        processor = CompressProcessor(max_context_tokens=10000)
        metrics = create_task_metrics(CHAT_ID)
        metrics.compression_ineffective_streak = 3

        messages = [HumanMessage(content="test")]
        context = _build_context(messages=messages)

        with (
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.calculate_context_budget",
                return_value=_FakeBudget(dynamic_threshold=100, dynamic_min_save=50),
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.estimate_messages_tokens",
                side_effect=[1000, 5000, 800],
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.compress_messages_async",
                new=AsyncMock(return_value=(messages, 200)),
            ),
            patch(
                "myrm_agent_harness.agent.context_management.infra.cache_break_detector.get_cache_break_detector",
                return_value=None,
            ),
        ):
            await processor.process(context)

        assert metrics.compression_ineffective_streak == 0

    @pytest.mark.asyncio
    async def test_ineffective_compression_increments_streak(self) -> None:
        """savings < 10% increments streak by 1."""
        processor = CompressProcessor(max_context_tokens=10000)
        metrics = create_task_metrics(CHAT_ID)
        metrics.compression_ineffective_streak = 1

        messages = [HumanMessage(content="test")]
        context = _build_context(messages=messages)

        with (
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.calculate_context_budget",
                return_value=_FakeBudget(dynamic_threshold=100, dynamic_min_save=50),
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.estimate_messages_tokens",
                side_effect=[1000, 5000, 950],
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.compress_messages_async",
                new=AsyncMock(return_value=(messages, 50)),
            ),
            patch(
                "myrm_agent_harness.agent.context_management.infra.cache_break_detector.get_cache_break_detector",
                return_value=None,
            ),
        ):
            await processor.process(context)

        assert metrics.compression_ineffective_streak == 2

    @pytest.mark.asyncio
    async def test_streak_persists_across_pipeline_rounds(self) -> None:
        """streak accumulates across multiple pipeline executions via TaskMetrics."""
        processor = CompressProcessor(max_context_tokens=10000)
        metrics = create_task_metrics(CHAT_ID)
        assert metrics.compression_ineffective_streak == 0

        messages = [HumanMessage(content="test")]

        for _round_num in range(3):
            context = _build_context(messages=messages)

            with (
                patch(
                    "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.calculate_context_budget",
                    return_value=_FakeBudget(dynamic_threshold=100, dynamic_min_save=50),
                ),
                patch(
                    "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.estimate_messages_tokens",
                    side_effect=[1000, 5000, 980],
                ),
                patch(
                    "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.compress_messages_async",
                    new=AsyncMock(return_value=(messages, 20)),
                ),
                patch(
                    "myrm_agent_harness.agent.context_management.infra.cache_break_detector.get_cache_break_detector",
                    return_value=None,
                ),
            ):
                await processor.process(context)

        assert metrics.compression_ineffective_streak == 3

    @pytest.mark.asyncio
    async def test_no_chat_id_does_not_crash(self) -> None:
        """Without chat_id, streak update is silently skipped."""
        processor = CompressProcessor(max_context_tokens=10000)
        messages = [HumanMessage(content="test")]
        context = ProcessorContext(
            messages=messages,
            user_query="test",
            chat_id=None,
            metadata={},
        )

        with (
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.calculate_context_budget",
                return_value=_FakeBudget(dynamic_threshold=100, dynamic_min_save=50),
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.estimate_messages_tokens",
                side_effect=[1000, 5000, 800],
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.compress_messages_async",
                new=AsyncMock(return_value=(messages, 200)),
            ),
            patch(
                "myrm_agent_harness.agent.context_management.infra.cache_break_detector.get_cache_break_detector",
                return_value=None,
            ),
        ):
            result = await processor.process(context)

        assert "compression_ineffective_streak" not in result.metadata


class TestAntiThrashingHotCacheInteraction:
    """Tests for anti-thrashing and hot cache bypass interaction."""

    @pytest.mark.asyncio
    async def test_hot_cache_bypass_checked_after_anti_thrashing(self) -> None:
        """When anti-thrashing skips, hot cache bypass is never reached."""
        processor = CompressProcessor(max_context_tokens=100000)
        metrics = create_task_metrics(CHAT_ID)
        metrics.compression_ineffective_streak = 3

        import time
        context = _build_context(
            metadata={"last_activity_time": time.time()},
        )

        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.calculate_context_budget",
            return_value=_FakeBudget(dynamic_threshold=50000),
        ), patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.estimate_messages_tokens",
            return_value=70000,
        ):
            result = await processor.should_process(context)

        assert result is False
        assert "compaction_debt_pending" not in context.metadata


class TestShouldProcessCoverage:
    """Additional should_process() coverage: below threshold, eco mode, hot cache bypass."""

    @pytest.mark.asyncio
    async def test_below_threshold_returns_false(self) -> None:
        """When tokens < dynamic_threshold, should_process returns False immediately."""
        processor = CompressProcessor(max_context_tokens=100000)
        context = _build_context()

        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.calculate_context_budget",
            return_value=_FakeBudget(dynamic_threshold=80000),
        ), patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.estimate_messages_tokens",
            return_value=50000,
        ):
            result = await processor.should_process(context)

        assert result is False

    @pytest.mark.asyncio
    async def test_eco_mode_lowers_threshold(self) -> None:
        """Eco mode reduces dynamic_threshold by 20%, allowing earlier compression."""
        processor = CompressProcessor(max_context_tokens=100000)
        context = _build_context(metadata={"eco_mode": True})

        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.calculate_context_budget",
            return_value=_FakeBudget(dynamic_threshold=70000),
        ), patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.estimate_messages_tokens",
            return_value=60000,
        ):
            result = await processor.should_process(context)

        assert result is True

    @pytest.mark.asyncio
    async def test_hot_cache_bypass_skips_compression(self) -> None:
        """Hot cache active + tokens < 90%: bypass compression, set compaction_debt_pending."""
        processor = CompressProcessor(max_context_tokens=100000)
        create_task_metrics(CHAT_ID)

        import time
        context = _build_context(
            metadata={"last_activity_time": time.time()},
        )

        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.calculate_context_budget",
            return_value=_FakeBudget(dynamic_threshold=50000),
        ), patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.estimate_messages_tokens",
            return_value=60000,
        ):
            result = await processor.should_process(context)

        assert result is False
        assert context.metadata.get("compaction_debt_pending") is True

    @pytest.mark.asyncio
    async def test_hot_cache_no_bypass_at_90_percent(self) -> None:
        """Hot cache active but tokens >= 90%: must compress (OOM risk)."""
        processor = CompressProcessor(max_context_tokens=100000)
        create_task_metrics(CHAT_ID)

        import time
        context = _build_context(
            metadata={"last_activity_time": time.time()},
        )

        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.calculate_context_budget",
            return_value=_FakeBudget(dynamic_threshold=50000),
        ), patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.estimate_messages_tokens",
            return_value=91000,
        ):
            result = await processor.should_process(context)

        assert result is True

    @pytest.mark.asyncio
    async def test_normal_trigger_above_threshold(self) -> None:
        """Above threshold, no anti-thrashing, no hot cache: returns True."""
        processor = CompressProcessor(max_context_tokens=100000)
        create_task_metrics(CHAT_ID)
        context = _build_context()

        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.calculate_context_budget",
            return_value=_FakeBudget(dynamic_threshold=50000),
        ), patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.estimate_messages_tokens",
            return_value=60000,
        ):
            result = await processor.should_process(context)

        assert result is True

    @pytest.mark.asyncio
    async def test_name_property(self) -> None:
        """name property returns 'compress'."""
        processor = CompressProcessor()
        assert processor.name == "compress"

    def test_is_eco_mode(self) -> None:
        """_is_eco_mode correctly reads metadata."""
        processor = CompressProcessor()
        assert processor._is_eco_mode(_build_context(metadata={"eco_mode": True}))
        assert not processor._is_eco_mode(_build_context(metadata={"eco_mode": False}))
        assert not processor._is_eco_mode(_build_context(metadata={}))


class TestBoundaryValues:
    """Boundary value tests for anti-thrashing thresholds."""

    @pytest.mark.asyncio
    async def test_streak_at_exactly_90_percent_forces_compression(self) -> None:
        """tokens = exactly 90% of max: safety net triggers."""
        processor = CompressProcessor(max_context_tokens=100000)
        metrics = create_task_metrics(CHAT_ID)
        metrics.compression_ineffective_streak = 2
        context = _build_context()

        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.calculate_context_budget",
            return_value=_FakeBudget(dynamic_threshold=50000),
        ), patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.estimate_messages_tokens",
            return_value=90000,
        ):
            result = await processor.should_process(context)

        assert result is True

    @pytest.mark.asyncio
    async def test_streak_just_below_90_percent_skips(self) -> None:
        """tokens = 89999 (just below 90%): anti-thrashing skips."""
        processor = CompressProcessor(max_context_tokens=100000)
        metrics = create_task_metrics(CHAT_ID)
        metrics.compression_ineffective_streak = 2
        context = _build_context()

        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.calculate_context_budget",
            return_value=_FakeBudget(dynamic_threshold=50000),
        ), patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.estimate_messages_tokens",
            return_value=89999,
        ):
            result = await processor.should_process(context)

        assert result is False

    @pytest.mark.asyncio
    async def test_no_metrics_defaults_streak_zero(self) -> None:
        """chat_id exists but no TaskMetrics created: streak defaults to 0."""
        processor = CompressProcessor(max_context_tokens=100000)
        context = _build_context()

        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.calculate_context_budget",
            return_value=_FakeBudget(dynamic_threshold=50000),
        ), patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.estimate_messages_tokens",
            return_value=60000,
        ):
            result = await processor.should_process(context)

        assert result is True

    @pytest.mark.asyncio
    async def test_savings_exactly_10_percent_resets_streak(self) -> None:
        """savings_pct = exactly 10%: treated as effective, resets streak."""
        processor = CompressProcessor(max_context_tokens=10000)
        metrics = create_task_metrics(CHAT_ID)
        metrics.compression_ineffective_streak = 2

        messages = [HumanMessage(content="test")]
        context = _build_context(messages=messages)

        with (
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.calculate_context_budget",
                return_value=_FakeBudget(dynamic_threshold=100, dynamic_min_save=50),
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.estimate_messages_tokens",
                side_effect=[1000, 5000, 800],
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.compress_messages_async",
                new=AsyncMock(return_value=(messages, 100)),
            ),
            patch(
                "myrm_agent_harness.agent.context_management.infra.cache_break_detector.get_cache_break_detector",
                return_value=None,
            ),
        ):
            await processor.process(context)

        assert metrics.compression_ineffective_streak == 0

    @pytest.mark.asyncio
    async def test_savings_just_below_10_percent_increments(self) -> None:
        """savings_pct = 9.9%: treated as ineffective, increments streak."""
        processor = CompressProcessor(max_context_tokens=10000)
        metrics = create_task_metrics(CHAT_ID)
        metrics.compression_ineffective_streak = 0

        messages = [HumanMessage(content="test")]
        context = _build_context(messages=messages)

        with (
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.calculate_context_budget",
                return_value=_FakeBudget(dynamic_threshold=100, dynamic_min_save=50),
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.estimate_messages_tokens",
                side_effect=[1000, 5000, 901],
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.compress_messages_async",
                new=AsyncMock(return_value=(messages, 99)),
            ),
            patch(
                "myrm_agent_harness.agent.context_management.infra.cache_break_detector.get_cache_break_detector",
                return_value=None,
            ),
        ):
            await processor.process(context)

        assert metrics.compression_ineffective_streak == 1

    @pytest.mark.asyncio
    async def test_streak_reset_then_reaccumulate(self) -> None:
        """streak resets on effective compression, then re-accumulates on ineffective."""
        processor = CompressProcessor(max_context_tokens=10000)
        metrics = create_task_metrics(CHAT_ID)
        messages = [HumanMessage(content="test")]

        for saved, expected_streak in [(20, 1), (20, 2), (200, 0), (20, 1)]:
            context = _build_context(messages=messages)
            with (
                patch(
                    "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.calculate_context_budget",
                    return_value=_FakeBudget(dynamic_threshold=100, dynamic_min_save=50),
                ),
                patch(
                    "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.estimate_messages_tokens",
                    side_effect=[1000, 5000, 800],
                ),
                patch(
                    "myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor.compress_messages_async",
                    new=AsyncMock(return_value=(messages, saved)),
                ),
                patch(
                    "myrm_agent_harness.agent.context_management.infra.cache_break_detector.get_cache_break_detector",
                    return_value=None,
                ),
            ):
                await processor.process(context)

            assert metrics.compression_ineffective_streak == expected_streak


class TestCachePreservationSkip:
    """Tests for Prompt Cache preservation skip in process()."""

    @pytest.mark.asyncio
    async def test_resume_skips_process(self) -> None:
        """is_resume=True causes process() to return early."""
        processor = CompressProcessor(max_context_tokens=10000)
        messages = [HumanMessage(content="test")]
        context = ProcessorContext(
            messages=messages,
            user_query="test",
            chat_id=CHAT_ID,
            is_resume=True,
            metadata={},
        )

        result = await processor.process(context)
        assert result.messages is messages

    @pytest.mark.asyncio
    async def test_hitl_session_skips_process(self) -> None:
        """hitl_session_active=True causes process() to return early."""
        processor = CompressProcessor(max_context_tokens=10000)
        messages = [HumanMessage(content="test")]
        context = ProcessorContext(
            messages=messages,
            user_query="test",
            chat_id=CHAT_ID,
            merged_context={"hitl_session_active": True},
            metadata={},
        )

        result = await processor.process(context)
        assert result.messages is messages


class TestHotCacheBypassEdgeCases:
    """Edge cases for _should_bypass_for_hot_cache."""

    def test_no_activity_time_does_not_bypass(self) -> None:
        """No last_activity_time in metadata: bypass does not trigger."""
        processor = CompressProcessor(max_context_tokens=100000)
        context = _build_context()
        assert not processor._should_bypass_for_hot_cache(context, 60000)

    def test_invalid_type_activity_time(self) -> None:
        """String last_activity_time: bypass does not trigger."""
        processor = CompressProcessor(max_context_tokens=100000)
        context = _build_context(metadata={"last_activity_time": "not_a_number"})
        assert not processor._should_bypass_for_hot_cache(context, 60000)

    def test_stale_activity_time(self) -> None:
        """last_activity_time older than 5 min: bypass does not trigger."""
        import time
        processor = CompressProcessor(max_context_tokens=100000)
        context = _build_context(
            metadata={"last_activity_time": time.time() - 400},
        )
        assert not processor._should_bypass_for_hot_cache(context, 60000)

    def test_hot_activity_time_triggers_bypass(self) -> None:
        """Recent last_activity_time + tokens < 90%: bypass triggers."""
        import time
        processor = CompressProcessor(max_context_tokens=100000)
        context = _build_context(
            metadata={"last_activity_time": time.time()},
        )
        assert processor._should_bypass_for_hot_cache(context, 60000)

    def test_hot_but_at_90_percent_no_bypass(self) -> None:
        """Recent last_activity_time but tokens >= 90%: no bypass (OOM risk)."""
        import time
        processor = CompressProcessor(max_context_tokens=100000)
        context = _build_context(
            metadata={"last_activity_time": time.time()},
        )
        assert not processor._should_bypass_for_hot_cache(context, 90000)
