"""DefaultAgentFactory resolves its LLM from injection, config or env and never fabricates one."""

from __future__ import annotations

import pytest
from langchain_core.language_models import FakeListChatModel

from myrm_agent_harness.agent.acp.default_factory import DefaultAgentFactory
from myrm_agent_harness.core.config.llm import LLMConfig
from myrm_agent_harness.toolkits.llms import ChatLiteLLM


@pytest.fixture(autouse=True)
def _no_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("MYRM_MODEL_NAME", "MYRM_API_KEY"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.asyncio
async def test_injected_llm_is_used_as_is() -> None:
    llm = FakeListChatModel(responses=["hi"])

    agent = await DefaultAgentFactory(llm=llm).create_agent("s1", "/tmp")

    assert agent.llm is llm


@pytest.mark.asyncio
async def test_llm_is_built_from_explicit_config() -> None:
    config = LLMConfig(model="gpt-4o-mini", api_key="sk-test")

    agent = await DefaultAgentFactory(llm_config=config).create_agent("s1", "/tmp")

    assert isinstance(agent.llm, ChatLiteLLM)
    assert agent.llm.model == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_llm_is_built_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYRM_MODEL_NAME", "gpt-4o-mini")
    monkeypatch.setenv("MYRM_API_KEY", "sk-test")

    agent = await DefaultAgentFactory().create_agent("s1", "/tmp")

    assert isinstance(agent.llm, ChatLiteLLM)
    assert agent.llm.model == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_missing_configuration_fails_instead_of_faking_a_model() -> None:
    with pytest.raises(ValueError, match="MYRM_MODEL_NAME"):
        await DefaultAgentFactory().create_agent("s1", "/tmp")
