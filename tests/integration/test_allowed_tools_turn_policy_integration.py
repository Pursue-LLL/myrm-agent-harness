"""Integration tests for turn tool policy on allowed_tools-incompatible gateways."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from myrm_agent_harness.agent.config.litellm_routing import (
    normalize_env_model_selection_string,
)
from myrm_agent_harness.agent.middlewares._session_context import (
    get_turn_allowed_tool_names,
    set_turn_allowed_tool_names,
)
from myrm_agent_harness.agent.middlewares._tool_helpers import check_trust_attenuation
from myrm_agent_harness.agent.middlewares.skill_attenuation_middleware import (
    SkillAttenuationMiddleware,
)
from myrm_agent_harness.agent.tool_management.registry import ToolRegistry
from myrm_agent_harness.toolkits.llms.allowed_tools_capability import (
    model_supports_allowed_tools_tool_choice,
)
from myrm_agent_harness.toolkits.llms.core.llm import create_litellm_model

pytestmark = [pytest.mark.integration, pytest.mark.timeout(90)]

_ENV_TEST = (
    Path(__file__).resolve().parents[3]
    / "myrm-agent"
    / "myrm-agent-server"
    / ".env.test"
)


@pytest.fixture(autouse=True)
def _load_env_test() -> None:
    if not _ENV_TEST.exists():
        pytest.skip(f"{_ENV_TEST} not found")
    for line in _ENV_TEST.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        if key and value:
            os.environ.setdefault(key, value)


def _get_basic_llm_config() -> tuple[str, str, str]:
    api_key = os.environ.get("BASIC_API_KEY", "")
    base_url = os.environ.get("BASIC_BASE_URL", "")
    model = os.environ.get("BASIC_MODEL", "")
    if not all([api_key, base_url, model]):
        pytest.skip("BASIC_API_KEY/BASIC_BASE_URL/BASIC_MODEL not configured")
    model = normalize_env_model_selection_string(model)
    return api_key, base_url, model


def _get_agnes_llm_config_from_env_test() -> tuple[str, str, str] | None:
    """Parse optional agnes credentials from commented lines in .env.test."""
    if not _ENV_TEST.exists():
        return None
    agnes_key = ""
    agnes_base = ""
    agnes_model = ""
    for line in _ENV_TEST.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("# BASIC_API_KEY=sk-"):
            agnes_key = stripped.split("=", 1)[1]
        elif stripped.startswith("# BASIC_BASE_URL=https://apihub.agnes"):
            agnes_base = stripped.split("=", 1)[1]
        elif stripped.startswith("# BASIC_MODEL=openai-like/agnes"):
            agnes_model = stripped.split("=", 1)[1]
    if all([agnes_key, agnes_base, agnes_model]):
        return agnes_key, agnes_base, normalize_env_model_selection_string(agnes_model)
    return None


@pytest.mark.asyncio
async def test_unsupported_gateway_skips_allowed_tools_but_execution_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_key, base_url, model = _get_basic_llm_config()
    assert model_supports_allowed_tools_tool_choice(model, api_base=base_url) is False

    monkeypatch.setattr(
        "myrm_agent_harness.agent._skill_agent_context.get_loaded_skills",
        lambda: None,
    )
    monkeypatch.setattr(
        "myrm_agent_harness.agent.middlewares.skill_attenuation_middleware.compute_turn_allowed_names",
        lambda *_args, **_kwargs: frozenset({"web_search_tool"}),
    )

    class _FakeRequest:
        def __init__(self) -> None:
            self.tools = [
                SimpleNamespace(name="web_search_tool"),
                SimpleNamespace(name="file_write_tool"),
            ]
            self.messages = [HumanMessage(content="请解释一下这个问题")]
            self.model = SimpleNamespace(
                model=model, model_name=model, api_base=base_url
            )
            self.tool_choice: dict[str, object] | None = None

        def override(self, *, tool_choice: dict[str, object]) -> _FakeRequest:
            self.tool_choice = tool_choice
            return self

    request = _FakeRequest()
    middleware = SkillAttenuationMiddleware(ToolRegistry())

    async def _handler(req: _FakeRequest) -> SimpleNamespace:
        return SimpleNamespace(result=req)

    response = await middleware.awrap_model_call(request, _handler)
    final_request = response.result
    assert final_request.tool_choice is None
    assert get_turn_allowed_tool_names() == frozenset({"web_search_tool"})
    assert check_trust_attenuation("web_search_tool") is None
    assert check_trust_attenuation("file_write_tool") is not None


@pytest.mark.asyncio
async def test_real_llm_invoke_without_allowed_tools_succeeds() -> None:
    api_key, base_url, model = _get_basic_llm_config()
    assert model_supports_allowed_tools_tool_choice(model, api_base=base_url) is False

    llm = create_litellm_model(
        model, base_url=base_url, api_key=api_key, streaming=False
    )
    result = await llm.ainvoke([HumanMessage(content="Reply with exactly: OK")])
    content = result.content
    assert isinstance(content, str)
    assert content.strip()

    set_turn_allowed_tool_names(None)


@pytest.mark.asyncio
@pytest.mark.timeout(120)
async def test_agnes_real_llm_invoke_without_allowed_tools_succeeds() -> None:
    agnes = _get_agnes_llm_config_from_env_test()
    if agnes is None:
        pytest.skip("agnes credentials not found in .env.test comments")
    api_key, base_url, model = agnes
    assert model_supports_allowed_tools_tool_choice(model, api_base=base_url) is False

    llm = create_litellm_model(
        model, base_url=base_url, api_key=api_key, streaming=False
    )
    result = await llm.ainvoke([HumanMessage(content="Reply with exactly: OK")])
    content = result.content
    assert isinstance(content, str)
    assert content.strip()

    set_turn_allowed_tool_names(None)
