"""Tests for SkillAttenuationMiddleware model-call tool narrowing."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import HumanMessage

from myrm_agent_harness.agent.middlewares.tooling.skill_attenuation_middleware import (
    SkillAttenuationMiddleware,
)
from myrm_agent_harness.agent.tool_management.registry import ToolRegistry


@dataclass(slots=True)
class _FakeRequest:
    tools: list[object]
    messages: list[object]
    model: object
    tool_choice: dict[str, object] | None = None

    def override(self, *, tool_choice: dict[str, object]) -> _FakeRequest:
        return _FakeRequest(
            tools=self.tools,
            messages=self.messages,
            model=self.model,
            tool_choice=tool_choice,
        )


@dataclass(slots=True)
class _FakeResponse:
    ok: bool = True


@pytest.mark.asyncio
async def test_skips_override_when_allowlist_becomes_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "myrm_agent_harness.agent.skill_agent.context.get_loaded_skills",
        lambda: None,
    )
    monkeypatch.setattr(
        "myrm_agent_harness.agent.middlewares.tooling.skill_attenuation_middleware.compute_turn_allowed_names",
        lambda *_args, **_kwargs: None,
    )

    request = _FakeRequest(
        tools=[
            SimpleNamespace(name="render_ui_tool"),
            SimpleNamespace(name="update_ui_data_tool"),
        ],
        messages=[HumanMessage(content="Please explain this issue.")],
        model=SimpleNamespace(model="gpt-4o", model_name="gpt-4o", api_base=None),
    )
    middleware = SkillAttenuationMiddleware(ToolRegistry())

    captured: dict[str, _FakeRequest] = {}

    async def _handler(req: _FakeRequest) -> _FakeResponse:
        captured["request"] = req
        return _FakeResponse()

    await middleware.awrap_model_call(request, _handler)
    assert captured["request"].tool_choice is None


@pytest.mark.asyncio
async def test_skips_tool_choice_for_block_all_empty_frozenset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "myrm_agent_harness.agent.skill_agent.context.get_loaded_skills",
        lambda: None,
    )
    monkeypatch.setattr(
        "myrm_agent_harness.agent.middlewares.tooling.skill_attenuation_middleware.compute_turn_allowed_names",
        lambda *_args, **_kwargs: frozenset(),
    )

    request = _FakeRequest(
        tools=[SimpleNamespace(name="bash_code_execute_tool")],
        messages=[HumanMessage(content="请分析这段日志为什么会失败？")],
        model=SimpleNamespace(model="gpt-4o", model_name="gpt-4o", api_base=None),
    )
    middleware = SkillAttenuationMiddleware(ToolRegistry())

    captured: dict[str, _FakeRequest] = {}

    async def _handler(req: _FakeRequest) -> _FakeResponse:
        captured["request"] = req
        return _FakeResponse()

    await middleware.awrap_model_call(request, _handler)
    assert captured["request"].tool_choice is None


@pytest.mark.asyncio
async def test_applies_allowed_tools_when_restriction_is_non_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "myrm_agent_harness.agent.skill_agent.context.get_loaded_skills",
        lambda: None,
    )
    monkeypatch.setattr(
        "myrm_agent_harness.agent.middlewares.tooling.skill_attenuation_middleware.compute_turn_allowed_names",
        lambda *_args, **_kwargs: frozenset({"web_search_tool"}),
    )
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.llms.allowed_tools_capability.model_supports_allowed_tools_tool_choice",
        lambda *_args, **_kwargs: True,
    )

    request = _FakeRequest(
        tools=[
            SimpleNamespace(name="render_ui_tool"),
            SimpleNamespace(name="web_search_tool"),
        ],
        messages=[HumanMessage(content="Please explain this issue.")],
        model=SimpleNamespace(model="gpt-4o", model_name="gpt-4o", api_base=None),
    )
    middleware = SkillAttenuationMiddleware(ToolRegistry())

    captured: dict[str, _FakeRequest] = {}

    async def _handler(req: _FakeRequest) -> _FakeResponse:
        captured["request"] = req
        return _FakeResponse()

    await middleware.awrap_model_call(request, _handler)
    tool_choice = captured["request"].tool_choice
    assert tool_choice is not None
    assert tool_choice["type"] == "allowed_tools"
    assert tool_choice["tools"] == [{"type": "function", "name": "web_search_tool"}]


@pytest.mark.asyncio
async def test_skips_allowed_tools_for_openai_like_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "myrm_agent_harness.agent.skill_agent.context.get_loaded_skills",
        lambda: None,
    )
    monkeypatch.setattr(
        "myrm_agent_harness.agent.middlewares.tooling.skill_attenuation_middleware.compute_turn_allowed_names",
        lambda *_args, **_kwargs: frozenset({"web_search_tool"}),
    )

    request = _FakeRequest(
        tools=[
            SimpleNamespace(name="render_ui_tool"),
            SimpleNamespace(name="web_search_tool"),
        ],
        messages=[HumanMessage(content="Please explain this issue.")],
        model=SimpleNamespace(
            model="openai-like/agnes-2.5-flash",
            model_name="openai-like/agnes-2.5-flash",
            api_base="https://apihub.agnes-ai.com/v1",
        ),
    )
    middleware = SkillAttenuationMiddleware(ToolRegistry())

    captured: dict[str, _FakeRequest] = {}

    async def _handler(req: _FakeRequest) -> _FakeResponse:
        captured["request"] = req
        return _FakeResponse()

    await middleware.awrap_model_call(request, _handler)
    assert captured["request"].tool_choice is None


def test_wrap_tool_call_delegates_when_tool_prebound() -> None:
    from langchain.agents.middleware.types import ToolCallRequest
    from langchain_core.messages import ToolMessage

    middleware = SkillAttenuationMiddleware(ToolRegistry())
    bound_tool = SimpleNamespace(name="ask_question_tool")
    request = ToolCallRequest(
        tool_call={"name": "ask_question_tool", "args": {}, "id": "call_1"},
        tool=bound_tool,
        state={},
        runtime=MagicMock(),
    )
    expected = ToolMessage(
        content="ok", name="ask_question_tool", tool_call_id="call_1"
    )

    def handler(req: ToolCallRequest) -> ToolMessage:
        assert req.tool is bound_tool
        return expected

    result = middleware.wrap_tool_call(request, handler)
    assert result is expected


def test_wrap_model_call_sync_skips_when_no_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "myrm_agent_harness.agent.middlewares._session_context.set_turn_allowed_tool_names",
        lambda _value: None,
    )

    request = _FakeRequest(
        tools=[],
        messages=[HumanMessage(content="hello")],
        model=SimpleNamespace(model="gpt-4o", model_name="gpt-4o", api_base=None),
    )
    middleware = SkillAttenuationMiddleware(ToolRegistry())
    captured: dict[str, _FakeRequest] = {}

    def _handler(req: _FakeRequest) -> _FakeResponse:
        captured["request"] = req
        return _FakeResponse()

    middleware.wrap_model_call(request, _handler)
    assert captured["request"].tool_choice is None


def test_wrap_tool_call_resolves_dynamic_tool_from_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langchain.agents.middleware.types import ToolCallRequest
    from langchain_core.messages import ToolMessage

    resolved_tool = SimpleNamespace(name="web_search_tool")
    registry = ToolRegistry()
    monkeypatch.setattr(registry, "resolve", lambda: [resolved_tool])
    monkeypatch.setattr(registry, "get_runtime_tools", lambda: [])

    middleware = SkillAttenuationMiddleware(registry)
    request = ToolCallRequest(
        tool_call={"name": "web_search_tool", "args": {}, "id": "call_2"},
        tool=None,
        state={},
        runtime=MagicMock(),
    )
    expected = ToolMessage(content="ok", name="web_search_tool", tool_call_id="call_2")

    def handler(req: ToolCallRequest) -> ToolMessage:
        assert req.tool is resolved_tool
        return expected

    assert middleware.wrap_tool_call(request, handler) is expected


@pytest.mark.asyncio
async def test_awrap_tool_call_resolves_dynamic_tool_from_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langchain.agents.middleware.types import ToolCallRequest
    from langchain_core.messages import ToolMessage

    resolved_tool = SimpleNamespace(name="file_read_tool")
    registry = ToolRegistry()
    monkeypatch.setattr(registry, "resolve", lambda: [resolved_tool])
    monkeypatch.setattr(registry, "get_runtime_tools", lambda: [])

    middleware = SkillAttenuationMiddleware(registry)
    request = ToolCallRequest(
        tool_call={"name": "file_read", "args": {}, "id": "call_3"},
        tool=None,
        state={},
        runtime=MagicMock(),
    )
    expected = ToolMessage(content="ok", name="file_read_tool", tool_call_id="call_3")

    async def handler(req: ToolCallRequest) -> ToolMessage:
        assert req.tool is resolved_tool
        return expected

    assert await middleware.awrap_tool_call(request, handler) is expected
