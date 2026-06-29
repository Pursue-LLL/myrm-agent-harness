"""Test auto_session_recall_middleware.

Validates idempotency, quick path, query extraction, threshold filtering,
RecallMode handling, timeout behavior, and injection semantics.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.agent.middlewares.auto_session_recall_middleware import (
    _SESSION_RECALL_MARKER,
    _extract_query,
    _format_recall_body,
    _has_session_recall,
    auto_session_recall_middleware,
)
from myrm_agent_harness.toolkits.memory.config import RecallMode
from myrm_agent_harness.toolkits.memory.types import MemoryType


def _make_search_result(content: str, score: float, mem_type: MemoryType = MemoryType.CONVERSATION) -> MagicMock:
    memory = MagicMock()
    memory.content = content
    memory.id = f"mem-{hash(content) % 10000:04d}"
    result = MagicMock()
    result.memory = memory
    result.score = score
    result.memory_type = mem_type
    return result


class TestHasSessionRecall:
    def test_detects_marker(self):
        messages = [
            SystemMessage(content="System"),
            HumanMessage(content=f'{_SESSION_RECALL_MARKER} count="2">\ndata\n</auto_session_recall>'),
        ]
        assert _has_session_recall(messages) is True

    def test_no_marker(self):
        messages = [
            SystemMessage(content="System"),
            HumanMessage(content="Hello, continue our project"),
        ]
        assert _has_session_recall(messages) is False

    def test_marker_only_in_human_messages(self):
        messages = [
            SystemMessage(content=f"Something {_SESSION_RECALL_MARKER}"),
            HumanMessage(content="Normal"),
        ]
        assert _has_session_recall(messages) is False


class TestExtractQuery:
    def test_extracts_first_human_message(self):
        messages = [
            SystemMessage(content="System prompt"),
            HumanMessage(content="Continue the API design discussion"),
        ]
        assert _extract_query(messages) == "Continue the API design discussion"

    def test_skips_recall_marker(self):
        messages = [
            HumanMessage(content=f'{_SESSION_RECALL_MARKER} count="1">\nold data\n</auto_session_recall>'),
            HumanMessage(content="Real user query here"),
        ]
        assert _extract_query(messages) == "Real user query here"

    def test_handles_multimodal_content(self):
        messages = [
            HumanMessage(content=[{"type": "text", "text": "What about the deployment?"}]),
        ]
        assert _extract_query(messages) == "What about the deployment?"

    def test_empty_messages(self):
        assert _extract_query([]) == ""

    def test_truncates_long_query(self):
        long_text = "A" * 3000
        messages = [HumanMessage(content=long_text)]
        result = _extract_query(messages)
        assert len(result) == 2000


class TestFormatRecallBody:
    def test_formats_results(self):
        results = [
            _make_search_result("We discussed caching strategy with Redis", 0.85),
            _make_search_result("Task: implement rate limiting", 0.78, MemoryType.TASK_DIGEST),
        ]
        body = _format_recall_body(results, budget_tokens=200)
        assert "caching strategy" in body
        assert "rate limiting" in body
        assert "[conversation]" in body
        assert "[task_digest]" in body
        assert "0.85" in body

    def test_respects_budget(self):
        results = [_make_search_result("A" * 500, 0.9) for _ in range(10)]
        body = _format_recall_body(results, budget_tokens=50)
        assert len(body) <= 50 * 4 + 100

    def test_truncates_long_content(self):
        results = [_make_search_result("X" * 800, 0.9)]
        body = _format_recall_body(results, budget_tokens=500)
        assert "..." in body


class TestMiddlewareIdempotency:
    @pytest.mark.asyncio
    async def test_skips_when_marker_present(self):
        handler = AsyncMock()

        request = MagicMock()
        request.messages = [
            SystemMessage(content="System"),
            HumanMessage(content=f'{_SESSION_RECALL_MARKER} count="1">\ndata\n</auto_session_recall>'),
            HumanMessage(content="Follow up question"),
        ]
        request.state = {"messages": list(request.messages)}

        await auto_session_recall_middleware.awrap_model_call(request, handler)
        handler.assert_called_once_with(request)


class TestMiddlewareQuickPath:
    @pytest.mark.asyncio
    async def test_skips_when_no_memories(self):
        handler = AsyncMock()

        manager = AsyncMock()
        manager.recall_mode = RecallMode.HYBRID
        manager.count_memories = AsyncMock(return_value=0)
        manager._config = MagicMock()
        manager._config.auto_session_recall_enabled = True
        manager._config.auto_session_recall_threshold = 0.72
        manager._config.auto_session_recall_budget_tokens = 800
        manager._config.auto_session_recall_timeout = 3.0

        request = MagicMock()
        request.messages = [
            SystemMessage(content="System"),
            HumanMessage(content="Tell me about the project architecture"),
        ]
        request.state = {"messages": []}
        request.runtime = MagicMock()
        request.runtime.context = {"memory_manager": manager}

        with patch(
            "myrm_agent_harness.agent._skill_agent_context.get_memory_manager",
            return_value=manager,
        ):
            await auto_session_recall_middleware.awrap_model_call(request, handler)

        handler.assert_called_once_with(request)
        manager.search.assert_not_called()


class TestMiddlewareRecallMode:
    @pytest.mark.asyncio
    async def test_skips_in_tools_mode(self):
        handler = AsyncMock()

        manager = AsyncMock()
        manager.recall_mode = RecallMode.TOOLS

        request = MagicMock()
        request.messages = [
            SystemMessage(content="System"),
            HumanMessage(content="Continue our architecture discussion"),
        ]
        request.state = {"messages": []}
        request.runtime = MagicMock()
        request.runtime.context = {"memory_manager": manager}

        with patch(
            "myrm_agent_harness.agent._skill_agent_context.get_memory_manager",
            return_value=manager,
        ):
            await auto_session_recall_middleware.awrap_model_call(request, handler)

        handler.assert_called_once_with(request)


class TestMiddlewareShortQuery:
    @pytest.mark.asyncio
    async def test_skips_short_query(self):
        handler = AsyncMock()

        manager = AsyncMock()
        manager.recall_mode = RecallMode.HYBRID

        request = MagicMock()
        request.messages = [
            SystemMessage(content="System"),
            HumanMessage(content="Hi"),
        ]
        request.state = {"messages": []}
        request.runtime = MagicMock()
        request.runtime.context = {"memory_manager": manager}

        with patch(
            "myrm_agent_harness.agent._skill_agent_context.get_memory_manager",
            return_value=manager,
        ):
            await auto_session_recall_middleware.awrap_model_call(request, handler)

        handler.assert_called_once_with(request)


class TestMiddlewareInjection:
    @pytest.mark.asyncio
    async def test_injects_high_score_results(self):
        handler = AsyncMock()

        results = [
            _make_search_result("Prior: We decided to use PostgreSQL for persistence", 0.85),
            _make_search_result("Prior: Redis for caching layer agreed", 0.78),
            _make_search_result("Low relevance item", 0.50),
        ]

        manager = AsyncMock()
        manager.recall_mode = RecallMode.HYBRID
        manager.count_memories = AsyncMock(return_value=15)
        manager.search = AsyncMock(return_value=results)
        manager._config = MagicMock()
        manager._config.auto_session_recall_enabled = True
        manager._config.auto_session_recall_threshold = 0.72
        manager._config.auto_session_recall_budget_tokens = 800
        manager._config.auto_session_recall_timeout = 3.0

        request = MagicMock()
        request.messages = [
            SystemMessage(content="System prompt"),
            HumanMessage(content="Let's continue with the database layer design"),
        ]
        request.state = {"messages": []}
        request.runtime = MagicMock()
        request.runtime.context = {"memory_manager": manager}
        request.override = MagicMock(return_value=request)

        with patch(
            "myrm_agent_harness.agent._skill_agent_context.get_memory_manager",
            return_value=manager,
        ):
            await auto_session_recall_middleware.awrap_model_call(request, handler)

        request.override.assert_called_once()
        injected_messages = request.override.call_args[1]["messages"]
        recall_msgs = [m for m in injected_messages if isinstance(m, HumanMessage) and _SESSION_RECALL_MARKER in m.content]
        assert len(recall_msgs) == 1
        recall_content = recall_msgs[0].content
        assert "PostgreSQL" in recall_content
        assert "Redis" in recall_content
        assert "Low relevance" not in recall_content

    @pytest.mark.asyncio
    async def test_skips_when_all_below_threshold(self):
        handler = AsyncMock()

        results = [
            _make_search_result("Unrelated topic", 0.50),
            _make_search_result("Another unrelated", 0.45),
        ]

        manager = AsyncMock()
        manager.recall_mode = RecallMode.HYBRID
        manager.count_memories = AsyncMock(return_value=10)
        manager.search = AsyncMock(return_value=results)
        manager._config = MagicMock()
        manager._config.auto_session_recall_enabled = True
        manager._config.auto_session_recall_threshold = 0.72
        manager._config.auto_session_recall_budget_tokens = 800
        manager._config.auto_session_recall_timeout = 3.0

        request = MagicMock()
        request.messages = [
            SystemMessage(content="System"),
            HumanMessage(content="Tell me a joke about programming"),
        ]
        request.state = {"messages": []}
        request.runtime = MagicMock()
        request.runtime.context = {"memory_manager": manager}

        with patch(
            "myrm_agent_harness.agent._skill_agent_context.get_memory_manager",
            return_value=manager,
        ):
            await auto_session_recall_middleware.awrap_model_call(request, handler)

        handler.assert_called_once_with(request)


class TestMiddlewareTimeout:
    @pytest.mark.asyncio
    async def test_graceful_timeout(self):
        handler = AsyncMock()

        async def slow_search(*args, **kwargs):
            await asyncio.sleep(10)
            return []

        manager = AsyncMock()
        manager.recall_mode = RecallMode.HYBRID
        manager.count_memories = AsyncMock(return_value=5)
        manager.search = slow_search
        manager._config = MagicMock()
        manager._config.auto_session_recall_enabled = True
        manager._config.auto_session_recall_threshold = 0.72
        manager._config.auto_session_recall_budget_tokens = 800
        manager._config.auto_session_recall_timeout = 0.1

        request = MagicMock()
        request.messages = [
            SystemMessage(content="System"),
            HumanMessage(content="Continue our discussion about testing"),
        ]
        request.state = {"messages": []}
        request.runtime = MagicMock()
        request.runtime.context = {"memory_manager": manager}

        with patch(
            "myrm_agent_harness.agent._skill_agent_context.get_memory_manager",
            return_value=manager,
        ):
            await auto_session_recall_middleware.awrap_model_call(request, handler)

        handler.assert_called_once_with(request)


class TestMiddlewareDisabled:
    @pytest.mark.asyncio
    async def test_skips_when_disabled(self):
        handler = AsyncMock()

        manager = AsyncMock()
        manager.recall_mode = RecallMode.HYBRID
        manager._config = MagicMock()
        manager._config.auto_session_recall_enabled = False

        request = MagicMock()
        request.messages = [
            SystemMessage(content="System"),
            HumanMessage(content="Continue our architecture discussion"),
        ]
        request.state = {"messages": []}
        request.runtime = MagicMock()
        request.runtime.context = {"memory_manager": manager}

        with patch(
            "myrm_agent_harness.agent._skill_agent_context.get_memory_manager",
            return_value=manager,
        ):
            await auto_session_recall_middleware.awrap_model_call(request, handler)

        handler.assert_called_once_with(request)
