"""Tests for role-scoped child delegation tool attachment."""

from __future__ import annotations

import pytest
from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.sub_agents.executor import SubagentExecutor
from myrm_agent_harness.agent.sub_agents.types import (
    DELEGATION_CAPABILITY_MANIFEST,
    ControlScope,
    DelegateRole,
    SubagentConfig,
)


class FakeSearchTool(BaseTool):
    name: str = "web_search_tool"
    description: str = "Search"

    def _run(self, query: str) -> str:
        return f"result: {query}"


class ChildAgentStub:
    def __init__(self) -> None:
        self._cached_tools: list[BaseTool] = [FakeSearchTool()]
        self.user_tools: list[BaseTool] = []
        self.added_tools: list[BaseTool] = []

    def add_tools(self, tools: list[BaseTool]) -> None:
        self.added_tools.extend(tools)


class CatalogStub:
    async def list_available(self) -> list[str]:
        return ["worker"]

    async def resolve(self, agent_type: str) -> SubagentConfig | None:
        if agent_type != "worker":
            return None
        return SubagentConfig(system_prompt="worker", description="Worker")


@pytest.mark.asyncio
async def test_leaf_role_does_not_attach_child_delegation_tools() -> None:
    child_agent = ChildAgentStub()

    await SubagentExecutor()._attach_child_delegation_tools(
        child_agent=child_agent,
        agent_type="worker",
        config=SubagentConfig(
            system_prompt="test",
            control_scope=ControlScope.LEAF,
            delegation_role=DelegateRole.LEAF,
        ),
    )

    assert child_agent.added_tools == []


@pytest.mark.asyncio
async def test_orchestrator_role_attaches_child_scoped_delegation_tools() -> None:
    child_agent = ChildAgentStub()

    await SubagentExecutor()._attach_child_delegation_tools(
        child_agent=child_agent,
        agent_type="coordinator",
        config=SubagentConfig(
            system_prompt="test",
            control_scope=ControlScope.ORCHESTRATOR,
            delegation_role=DelegateRole.ORCHESTRATOR,
            delegation_catalog=CatalogStub(),
            delegation_allowed_types=frozenset({"worker"}),
        ),
    )

    assert tuple(tool.name for tool in child_agent.added_tools) == (
        DELEGATION_CAPABILITY_MANIFEST.orchestrator_child_tools
    )


@pytest.mark.asyncio
async def test_orchestrator_without_catalog_skips_attachment() -> None:
    child_agent = ChildAgentStub()

    await SubagentExecutor()._attach_child_delegation_tools(
        child_agent=child_agent,
        agent_type="coordinator",
        config=SubagentConfig(
            system_prompt="test",
            delegation_role=DelegateRole.ORCHESTRATOR,
            delegation_catalog=None,
        ),
    )

    assert child_agent.added_tools == []


@pytest.mark.asyncio
async def test_orchestrator_uses_user_tools_when_cache_empty() -> None:
    child_agent = ChildAgentStub()
    child_agent._cached_tools = []
    child_agent.user_tools = [FakeSearchTool()]

    await SubagentExecutor()._attach_child_delegation_tools(
        child_agent=child_agent,
        agent_type="coordinator",
        config=SubagentConfig(
            system_prompt="test",
            delegation_role=DelegateRole.ORCHESTRATOR,
            delegation_catalog=CatalogStub(),
        ),
    )

    assert child_agent.added_tools
