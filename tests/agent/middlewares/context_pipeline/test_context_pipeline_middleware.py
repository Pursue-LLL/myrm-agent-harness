"""Tests for context pipeline middleware — branch coverage for the rare paths.

Covers factory creation (notes manager wiring), custom vs dynamic pipeline
selection, awrap_model_call branches (notes load, resume overflow, eco mode,
cache TTL prune event, compression event, summary persist, cache-break
detector recording), and the standalone helpers (_count_tool_calls,
_extract_last_message_db_id, _safe_persist_summary).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.pipeline import (
    ContextPipeline,
    ProcessorContext,
)
from myrm_agent_harness.agent.context_management.pipeline.base import BaseProcessor
from myrm_agent_harness.agent.middlewares.context_pipeline.context_pipeline_middleware import (
    _count_tool_calls,
    _extract_last_message_db_id,
    _safe_persist_summary,
    create_context_pipeline_middleware,
)


class _NoOpProcessor(BaseProcessor):
    name = "noop"

    async def should_process(self, context: ProcessorContext) -> bool:
        return False

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        return context


def _mock_llm() -> MagicMock:
    llm = MagicMock()
    llm.model = "test-model"
    llm.api_base = ""
    return llm


def _request(llm: MagicMock, *, context: dict[str, object] | None = None) -> ModelRequest:
    from langgraph.runtime import Runtime

    return ModelRequest(
        model=llm,
        messages=[HumanMessage(content="hi")],
        runtime=Runtime(context=context or {"chat_id": "chat-1", "max_context_tokens": 128000}),
    )


def _result(messages: list | None = None, **overrides) -> ProcessorContext:
    ctx = ProcessorContext(
        messages=messages or [HumanMessage(content="hi")],
        user_query="",
        user_id="u1",
        chat_id="chat-1",
        llm=_mock_llm(),
    )
    for key, value in overrides.items():
        setattr(ctx, key, value)
    return ctx


class TestFactory:
    def test_notes_manager_wired_when_llm_provided(self) -> None:
        middleware = create_context_pipeline_middleware(
            llm=_mock_llm(),
            session_notes_llm=_mock_llm(),
        )
        assert getattr(middleware, "session_notes_manager", None) is not None

    def test_notes_manager_none_without_llm(self) -> None:
        middleware = create_context_pipeline_middleware(llm=_mock_llm())
        assert getattr(middleware, "session_notes_manager", None) is None

    def test_get_tools_returns_file_read_tool(self) -> None:
        middleware = create_context_pipeline_middleware(llm=_mock_llm())
        with patch(
            "myrm_agent_harness.agent.meta_tools.create_file_read_tool",
            return_value="file_read_tool",
        ) as mock_create:
            tools = middleware.get_tools()  # type: ignore[attr-defined]
        mock_create.assert_called_once()
        assert tools == ["file_read_tool"]

    def test_custom_pipeline_used_as_is(self) -> None:
        pipeline = ContextPipeline([_NoOpProcessor()])
        middleware = create_context_pipeline_middleware(llm=_mock_llm(), pipeline=pipeline)
        assert middleware is not None


class TestAwrapModelCall:
    @pytest.mark.asyncio
    async def test_basic_passthrough(self) -> None:
        pipeline = ContextPipeline([_NoOpProcessor()])
        middleware = create_context_pipeline_middleware(llm=_mock_llm(), pipeline=pipeline)
        llm = _mock_llm()
        request = _request(llm)
        handler = AsyncMock(return_value=ModelResponse(result=[]))
        response = await middleware.awrap_model_call(request, handler)
        handler.assert_awaited_once_with(request)
        assert response is handler.return_value

    @pytest.mark.asyncio
    async def test_dynamic_pipeline_creation(self) -> None:
        llm = _mock_llm()
        fake_pipeline = MagicMock()
        fake_pipeline.process = AsyncMock(return_value=_result())
        fake_pipeline_cls = MagicMock(return_value=fake_pipeline)
        with (
            patch(
                "myrm_agent_harness.agent.middlewares.context_pipeline.context_pipeline_middleware.build_default_processors",
                return_value=[],
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.context_pipeline.context_pipeline_middleware.ContextPipeline",
                fake_pipeline_cls,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.context_pipeline.context_pipeline_middleware.resolve_cache_ttl_prune_policy",
                return_value=SimpleNamespace(model_family="default", config=None),
            ),
        ):
            middleware = create_context_pipeline_middleware(llm=llm)
            request = _request(llm)
            handler = AsyncMock(return_value=ModelResponse(result=[]))
            await middleware.awrap_model_call(request, handler)
        fake_pipeline.process.assert_awaited_once()
        handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_notes_load_success_and_failure(self) -> None:
        llm = _mock_llm()
        pipeline = ContextPipeline([_NoOpProcessor()])
        notes_llm = _mock_llm()
        on_notes_load = AsyncMock(return_value='{"_meta": {"last_updated_message_idx": 0}, "progress": "notes"}')
        middleware = create_context_pipeline_middleware(
            llm=llm,
            pipeline=pipeline,
            session_notes_llm=notes_llm,
            on_notes_load=on_notes_load,
        )
        request = _request(llm)
        handler = AsyncMock(return_value=ModelResponse(result=[]))
        await middleware.awrap_model_call(request, handler)
        on_notes_load.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_notes_load_exception_is_non_blocking(self) -> None:
        llm = _mock_llm()
        pipeline = ContextPipeline([_NoOpProcessor()])
        notes_llm = _mock_llm()
        on_notes_load = AsyncMock(side_effect=RuntimeError("db down"))
        middleware = create_context_pipeline_middleware(
            llm=llm,
            pipeline=pipeline,
            session_notes_llm=notes_llm,
            on_notes_load=on_notes_load,
        )
        request = _request(llm)
        handler = AsyncMock(return_value=ModelResponse(result=[]))
        await middleware.awrap_model_call(request, handler)
        handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_resume_overflow_raises(self) -> None:
        llm = _mock_llm()
        pipeline = ContextPipeline([_NoOpProcessor()])
        middleware = create_context_pipeline_middleware(llm=llm, pipeline=pipeline)
        request = _request(
            llm,
            context={
                "chat_id": "chat-1",
                "max_context_tokens": 3,
                "is_resume": True,
            },
        )
        handler = AsyncMock()
        with pytest.raises(ValueError, match="Resume failed"):
            await middleware.awrap_model_call(request, handler)

    @pytest.mark.asyncio
    async def test_eco_mode_budget_pressure(self) -> None:
        llm = _mock_llm()
        seen: dict[str, object] = {}

        class _CapturePipeline:
            async def process(self, context: ProcessorContext) -> ProcessorContext:
                seen["eco_mode"] = context.metadata.get("eco_mode")
                return context

        middleware = create_context_pipeline_middleware(
            llm=llm,
            pipeline=_CapturePipeline(),  # type: ignore[arg-type]
            budget_pressure_fn=lambda: True,
        )
        request = _request(llm)
        handler = AsyncMock(return_value=ModelResponse(result=[]))
        await middleware.awrap_model_call(request, handler)
        assert seen["eco_mode"] is True

    @pytest.mark.asyncio
    async def test_budget_pressure_exception_is_non_blocking(self) -> None:
        llm = _mock_llm()
        pipeline = ContextPipeline([_NoOpProcessor()])
        middleware = create_context_pipeline_middleware(
            llm=llm,
            pipeline=pipeline,
            budget_pressure_fn=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        request = _request(llm)
        handler = AsyncMock(return_value=ModelResponse(result=[]))
        await middleware.awrap_model_call(request, handler)
        handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cache_ttl_prune_event_dispatched(self) -> None:
        llm = _mock_llm()
        pipeline = MagicMock()
        pipeline.process = AsyncMock(
            return_value=_result(
                tokens_saved=100,
                operations=["cache_ttl_prune"],
                metadata={"context_snapshot_path": "/tmp/snap.jsonl"},
            )
        )
        middleware = create_context_pipeline_middleware(llm=llm, pipeline=pipeline)
        request = _request(llm)
        handler = AsyncMock(return_value=ModelResponse(result=[]))
        with patch(
            "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
            new_callable=AsyncMock,
        ) as mock_dispatch:
            await middleware.awrap_model_call(request, handler)
        assert mock_dispatch.await_count >= 1
        first_payload = mock_dispatch.await_args.args[1]
        assert first_payload["step_key"] == "context_pruned"

    @pytest.mark.asyncio
    async def test_compress_event_dispatched(self) -> None:
        llm = _mock_llm()
        pipeline = MagicMock()
        pipeline.process = AsyncMock(
            return_value=_result(
                tokens_saved=500,
                operations=["compress"],
                metadata={"context_snapshot_path": "/tmp/snap.jsonl"},
            )
        )
        middleware = create_context_pipeline_middleware(llm=llm, pipeline=pipeline)
        request = _request(llm)
        handler = AsyncMock(return_value=ModelResponse(result=[]))
        with (
            patch(
                "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
                new_callable=AsyncMock,
            ) as mock_dispatch,
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_integrity_guard._integrity_guards",
                {},
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.notify_loop_guard_compaction",
            ),
        ):
            await middleware.awrap_model_call(request, handler)
        assert mock_dispatch.await_count >= 1
        handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_summary_persist_task_scheduled(self) -> None:
        llm = _mock_llm()
        pipeline = MagicMock()
        pipeline.process = AsyncMock(
            return_value=_result(
                tokens_saved=0,
                operations=[],
                structured_summary=SimpleNamespace(),
            )
        )
        on_summary_persist = AsyncMock()
        middleware = create_context_pipeline_middleware(
            llm=llm,
            pipeline=pipeline,
            on_summary_persist=on_summary_persist,
        )
        request = _request(llm)
        handler = AsyncMock(return_value=ModelResponse(result=[]))
        await middleware.awrap_model_call(request, handler)
        import asyncio

        await asyncio.sleep(0.05)
        on_summary_persist.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_detector_records_prompt_state(self) -> None:
        llm = _mock_llm()
        pipeline = ContextPipeline([_NoOpProcessor()])
        middleware = create_context_pipeline_middleware(llm=llm, pipeline=pipeline)
        detector = MagicMock()
        request = _request(llm)
        handler = AsyncMock(return_value=ModelResponse(result=[]))
        with patch(
            "myrm_agent_harness.agent.context_management.infra.cache_break_detector._detector_var",
            SimpleNamespace(get=lambda: detector),
        ):
            await middleware.awrap_model_call(request, handler)
        detector.record_prompt_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_tool_pair_integrity_reruns(self) -> None:
        llm = _mock_llm()
        pipeline = MagicMock()
        # AIMessage with a tool call but no matching ToolMessage — integrity
        # guard must drop the orphan call, so guarded_messages is not the same object.
        messages = [
            HumanMessage(content="run"),
            AIMessage(content="", tool_calls=[{"id": "call_1", "name": "bash_code_execute_tool", "args": {}}]),
        ]
        pipeline.process = AsyncMock(return_value=_result(messages))
        middleware = create_context_pipeline_middleware(llm=llm, pipeline=pipeline)
        request = _request(llm)
        handler = AsyncMock(return_value=ModelResponse(result=[]))
        await middleware.awrap_model_call(request, handler)
        handler.assert_awaited_once()


class TestHelpers:
    def test_count_tool_calls(self) -> None:
        messages = [
            HumanMessage(content="a"),
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "1", "name": "bash_code_execute_tool", "args": {}},
                    {"id": "2", "name": "bash_code_execute_tool", "args": {}},
                ],
            ),
            AIMessage(content="", tool_calls=[{"id": "3", "name": "bash_code_execute_tool", "args": {}}]),
            ToolMessage(content="ok", tool_call_id="1"),
            HumanMessage(content="b"),
        ]
        assert _count_tool_calls(messages) == 3

    def test_count_tool_calls_ignores_non_ai(self) -> None:
        messages = [HumanMessage(content="a"), ToolMessage(content="ok", tool_call_id="1")]
        assert _count_tool_calls(messages) == 0

    def test_extract_last_message_db_id_dict_context(self) -> None:
        request = _request(_mock_llm(), context={"last_message_db_id": 42})
        assert _extract_last_message_db_id(request) == "42"

    def test_extract_last_message_db_id_missing(self) -> None:
        request = _request(_mock_llm())
        assert _extract_last_message_db_id(request) is None

    def test_extract_last_message_db_id_no_runtime(self) -> None:
        llm = _mock_llm()
        request = ModelRequest(model=llm, messages=[HumanMessage(content="hi")])
        assert _extract_last_message_db_id(request) is None

    @pytest.mark.asyncio
    async def test_safe_persist_summary_success(self) -> None:
        callback = AsyncMock()
        result = _result(tokens_saved=100, structured_summary=SimpleNamespace())
        await _safe_persist_summary(callback, "chat-1", result)
        callback.assert_awaited_once_with(
            chat_id="chat-1",
            summary=result.structured_summary,
            before_message_id="",
            tokens_saved=100,
        )

    @pytest.mark.asyncio
    async def test_safe_persist_summary_failure(self) -> None:
        callback = AsyncMock(side_effect=RuntimeError("db down"))
        result = _result(tokens_saved=100, structured_summary=SimpleNamespace())
        await _safe_persist_summary(callback, "chat-1", result)
        callback.assert_awaited_once()
