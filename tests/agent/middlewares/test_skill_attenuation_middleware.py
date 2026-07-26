"""Tests for SkillAttenuationMiddleware model-call tool narrowing."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from myrm_agent_harness.agent.middlewares.skill_attenuation_middleware import (
    SkillAttenuationMiddleware,
)
from myrm_agent_harness.agent.tool_management.registry import ToolRegistry


@dataclass(slots=True)
class _FakeRequest:
    tools: list[object]
    messages: list[object]
    tool_choice: dict[str, object] | None = None

    def override(self, *, tool_choice: dict[str, object]) -> _FakeRequest:
        return _FakeRequest(
            tools=self.tools,
            messages=self.messages,
            tool_choice=tool_choice,
        )


@dataclass(slots=True)
class _FakeResponse:
    ok: bool = True


@pytest.mark.asyncio
async def test_skips_override_when_allowlist_becomes_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "myrm_agent_harness.agent._skill_agent_context.get_loaded_skills",
        lambda: None,
    )
    monkeypatch.setattr(
        "myrm_agent_harness.agent.middlewares.skill_attenuation_middleware.extract_recent_human_text",
        lambda _messages: "explain root cause",
    )
    monkeypatch.setattr(
        "myrm_agent_harness.agent.middlewares.skill_attenuation_middleware.derive_runtime_allowed_tools",
        lambda **_kwargs: (frozenset(), ("readonly_intent_gate",)),
    )

    request = _FakeRequest(
        tools=[
            SimpleNamespace(name="render_ui_tool"),
            SimpleNamespace(name="update_ui_data_tool"),
        ],
        messages=[HumanMessage(content="Please explain this issue.")],
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
        "myrm_agent_harness.agent._skill_agent_context.get_loaded_skills",
        lambda: None,
    )
    monkeypatch.setattr(
        "myrm_agent_harness.agent.middlewares.skill_attenuation_middleware.extract_recent_human_text",
        lambda _messages: "Please explain this issue.",
    )
    monkeypatch.setattr(
        "myrm_agent_harness.agent.middlewares.skill_attenuation_middleware.derive_runtime_allowed_tools",
        lambda **_kwargs: (frozenset({"web_search_tool"}), ("readonly_intent_gate",)),
    )

    request = _FakeRequest(
        tools=[
            SimpleNamespace(name="render_ui_tool"),
            SimpleNamespace(name="web_search_tool"),
        ],
        messages=[HumanMessage(content="Please explain this issue.")],
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
