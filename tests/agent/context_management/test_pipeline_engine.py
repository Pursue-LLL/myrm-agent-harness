"""Tests for ContextPipeline core operations (process, add, remove)."""

import asyncio

import pytest
from langchain_core.messages import HumanMessage

from myrm_agent_harness.agent.context_management.infra.session_lock import (
    acquire_context_lock,
    clear_all_locks,
    get_active_session_count,
    is_context_lock_held,
    reset_current_chat_id,
    set_current_chat_id,
)
from myrm_agent_harness.agent.context_management.pipeline.base import BaseProcessor, ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.engine import ContextPipeline, create_default_pipeline


class PassthroughProcessor(BaseProcessor):
    """Always runs, no-op."""

    def __init__(self, proc_name: str = "passthrough") -> None:
        self._name = proc_name

    @property
    def name(self) -> str:
        return self._name

    async def should_process(self, context: ProcessorContext) -> bool:
        return True

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        return context


class SkipProcessor(BaseProcessor):
    """Always skips."""

    def __init__(self, proc_name: str = "skip") -> None:
        self._name = proc_name

    @property
    def name(self) -> str:
        return self._name

    async def should_process(self, context: ProcessorContext) -> bool:
        return False

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        raise AssertionError("Should not be called")


class FailingProcessor(BaseProcessor):
    """Raises during process."""

    def __init__(self, proc_name: str = "fail") -> None:
        self._name = proc_name

    @property
    def name(self) -> str:
        return self._name

    async def should_process(self, context: ProcessorContext) -> bool:
        return True

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        raise RuntimeError("Intentional failure")


class LockProbeProcessor(BaseProcessor):
    """Records lock state and overlaps while running."""

    active_count = 0
    max_active_count = 0

    def __init__(self, started: asyncio.Event | None = None, release: asyncio.Event | None = None) -> None:
        self.started = started
        self.release = release
        self.lock_states: list[bool] = []

    @property
    def name(self) -> str:
        return "lock_probe"

    async def should_process(self, context: ProcessorContext) -> bool:
        return True

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        self.lock_states.append(is_context_lock_held(context.chat_id))
        LockProbeProcessor.active_count += 1
        LockProbeProcessor.max_active_count = max(
            LockProbeProcessor.max_active_count,
            LockProbeProcessor.active_count,
        )
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            await self.release.wait()
        else:
            await asyncio.sleep(0)
        LockProbeProcessor.active_count -= 1
        return context


def _make_context() -> ProcessorContext:
    return ProcessorContext(messages=[HumanMessage(content="test")], user_query="test")


class TestContextPipeline:
    """Tests for ContextPipeline."""

    @pytest.mark.asyncio
    async def test_empty_pipeline(self) -> None:
        pipeline = ContextPipeline([])
        ctx = _make_context()
        result = await pipeline.process(ctx)
        assert result.operations == []

    @pytest.mark.asyncio
    async def test_single_processor_runs(self) -> None:
        pipeline = ContextPipeline([PassthroughProcessor("p1")])
        ctx = _make_context()
        result = await pipeline.process(ctx)
        assert "p1" in result.operations

    @pytest.mark.asyncio
    async def test_multiple_processors_order(self) -> None:
        pipeline = ContextPipeline(
            [
                PassthroughProcessor("a"),
                PassthroughProcessor("b"),
                PassthroughProcessor("c"),
            ]
        )
        ctx = _make_context()
        result = await pipeline.process(ctx)
        assert result.operations == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_skipped_processor_not_in_operations(self) -> None:
        pipeline = ContextPipeline(
            [
                PassthroughProcessor("run"),
                SkipProcessor("skip"),
                PassthroughProcessor("run2"),
            ]
        )
        ctx = _make_context()
        result = await pipeline.process(ctx)
        assert result.operations == ["run", "run2"]

    @pytest.mark.asyncio
    async def test_failing_processor_does_not_break_pipeline(self) -> None:
        pipeline = ContextPipeline(
            [
                PassthroughProcessor("before"),
                FailingProcessor("fail"),
                PassthroughProcessor("after"),
            ]
        )
        ctx = _make_context()
        result = await pipeline.process(ctx)
        assert "before" in result.operations
        assert "fail" not in result.operations
        assert "after" in result.operations

    def test_add_processor(self) -> None:
        pipeline = ContextPipeline()
        ret = pipeline.add_processor(PassthroughProcessor("new"))
        assert ret is pipeline
        assert len(pipeline.processors) == 1
        assert pipeline.processors[0].name == "new"

    def test_remove_processor_found(self) -> None:
        pipeline = ContextPipeline(
            [
                PassthroughProcessor("a"),
                PassthroughProcessor("b"),
            ]
        )
        assert pipeline.remove_processor("a") is True
        assert len(pipeline.processors) == 1
        assert pipeline.processors[0].name == "b"

    def test_remove_processor_not_found(self) -> None:
        pipeline = ContextPipeline([PassthroughProcessor("a")])
        assert pipeline.remove_processor("nonexistent") is False
        assert len(pipeline.processors) == 1

    def test_create_default_pipeline(self) -> None:
        pipeline = create_default_pipeline(max_context_tokens=32000)
        assert isinstance(pipeline, ContextPipeline)
        assert len(pipeline.processors) > 0

    def test_init_with_none_processors(self) -> None:
        pipeline = ContextPipeline(None)
        assert pipeline.processors == []

    @pytest.mark.asyncio
    async def test_pipeline_holds_session_lock_for_chat_context(self) -> None:
        await clear_all_locks()
        processor = LockProbeProcessor()
        pipeline = ContextPipeline([processor])
        ctx = ProcessorContext(
            messages=[HumanMessage(content="test")],
            user_query="test",
            chat_id="chat-lock-held",
        )

        await pipeline.process(ctx)

        assert processor.lock_states == [True]

    @pytest.mark.asyncio
    async def test_pipeline_serializes_same_chat_context_mutations(self) -> None:
        await clear_all_locks()
        LockProbeProcessor.active_count = 0
        LockProbeProcessor.max_active_count = 0
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        first_processor = LockProbeProcessor(started=first_started, release=release_first)
        second_processor = LockProbeProcessor()
        first_pipeline = ContextPipeline([first_processor])
        second_pipeline = ContextPipeline([second_processor])
        first_context = ProcessorContext(
            messages=[HumanMessage(content="first")],
            user_query="first",
            chat_id="same-chat",
        )
        second_context = ProcessorContext(
            messages=[HumanMessage(content="second")],
            user_query="second",
            chat_id="same-chat",
        )

        first_task = asyncio.create_task(first_pipeline.process(first_context))
        await first_started.wait()
        second_task = asyncio.create_task(second_pipeline.process(second_context))
        await asyncio.sleep(0)

        assert second_processor.lock_states == []

        release_first.set()
        await asyncio.gather(first_task, second_task)

        assert first_processor.lock_states == [True]
        assert second_processor.lock_states == [True]
        assert LockProbeProcessor.max_active_count == 1

    @pytest.mark.asyncio
    async def test_pipeline_does_not_lock_anonymous_context(self) -> None:
        await clear_all_locks()
        processor = LockProbeProcessor()
        pipeline = ContextPipeline([processor])

        await pipeline.process(_make_context())

        assert processor.lock_states == [False]
        assert get_active_session_count() == 0

    @pytest.mark.asyncio
    async def test_pipeline_uses_contextvar_chat_id_and_allows_reentrant_lock(self) -> None:
        await clear_all_locks()
        processor = LockProbeProcessor()
        pipeline = ContextPipeline([processor])
        token = set_current_chat_id("contextvar-chat")
        try:
            async with acquire_context_lock():
                result = await asyncio.wait_for(pipeline.process(_make_context()), timeout=1)
        finally:
            reset_current_chat_id(token)

        assert result.operations == ["lock_probe"]
        assert processor.lock_states == [True]
