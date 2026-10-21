"""debug_logger_middleware 单元测试

覆盖 ToolMessage content 为 str / list / 空三种形态，
回归防护：结构化工具结果（list content）不得导致 AttributeError。
"""

from unittest.mock import AsyncMock

import pytest
from langchain.agents.middleware import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from myrm_agent_harness.agent.middlewares.debug_logger_middleware import (
    DebugLoggerMiddleware,
)


@pytest.fixture
def middleware() -> DebugLoggerMiddleware:
    return DebugLoggerMiddleware()


def _build_request(content: object) -> ModelRequest:
    """构造包含指定 ToolMessage content 的模型请求。"""
    messages = [
        SystemMessage(content="system"),
        HumanMessage(content="hello"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "bash_code_execute_tool",
                    "args": {"code": "pwd"},
                    "id": "call_1",
                }
            ],
        ),
        ToolMessage(
            content=content, tool_call_id="call_1", name="bash_code_execute_tool"
        ),
    ]
    return ModelRequest(model=AsyncMock(), messages=messages)


@pytest.mark.asyncio
async def test_string_content_passes_through(middleware: DebugLoggerMiddleware) -> None:
    handler = AsyncMock()
    await middleware.awrap_model_call(
        _build_request("ls: No such file or directory"), handler
    )
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_content_structured_tool_result(
    middleware: DebugLoggerMiddleware,
) -> None:
    # 回归：结构化/多部分工具结果 content 为 list，此前在 startswith 处崩溃
    content = [
        {"type": "text", "text": "workspace contains 3 files"},
        {"type": "file", "path": "/tmp/wb_bench/readme.md"},
    ]
    handler = AsyncMock()
    await middleware.awrap_model_call(_build_request(content), handler)
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_empty_string_content(middleware: DebugLoggerMiddleware) -> None:
    handler = AsyncMock()
    await middleware.awrap_model_call(_build_request(""), handler)
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_empty_list_content(middleware: DebugLoggerMiddleware) -> None:
    handler = AsyncMock()
    await middleware.awrap_model_call(_build_request([]), handler)
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_system_message_branch(middleware: DebugLoggerMiddleware) -> None:
    """system_message attribute takes precedence over system_prompt."""
    request = ModelRequest(
        model=AsyncMock(),
        messages=[HumanMessage(content="hi")],
        system_message=SystemMessage(content="sys-msg-text"),
    )
    handler = AsyncMock()
    await middleware.awrap_model_call(request, handler)
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_system_prompt_only_branch(middleware: DebugLoggerMiddleware) -> None:
    """Without system_message, system_prompt is logged."""
    request = ModelRequest(
        model=AsyncMock(),
        messages=[HumanMessage(content="hi")],
        system_prompt="prompt-only",
    )
    handler = AsyncMock()
    await middleware.awrap_model_call(request, handler)
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_system_source_branch(middleware: DebugLoggerMiddleware) -> None:
    """Neither system_message nor system_prompt -> (none) logged."""
    request = ModelRequest(model=AsyncMock(), messages=[HumanMessage(content="hi")])
    handler = AsyncMock()
    await middleware.awrap_model_call(request, handler)
    handler.assert_awaited_once()


def test_format_content_ellipsis() -> None:
    """Long content is truncated with an omitted-chars summary."""
    from myrm_agent_harness.agent.middlewares.debug_logger_middleware import (
        _format_content,
    )

    long = "x" * 500
    result = _format_content(long)
    assert "(omitted" in result
    assert "chars" in result


def test_format_content_empty() -> None:
    from myrm_agent_harness.agent.middlewares.debug_logger_middleware import (
        _format_content,
    )

    assert _format_content("") == "(empty)"
