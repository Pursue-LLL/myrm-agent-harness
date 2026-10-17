"""Integration tests for the bound skill catalog around HITL resume and stream prep (real checkpoint, no mock aget_state)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, MessagesState, StateGraph

from myrm_agent_harness.agent._internals.skill_catalog_turn import (
    deliver_bound_skills_catalog,
    sync_bound_skills_for_resume,
)
from myrm_agent_harness.agent._internals.turn_history import TurnHistory
from myrm_agent_harness.agent.meta_tools.discover_capability.discover_capability_tool import (
    sync_discover_capability_tool,
)
from myrm_agent_harness.agent.middlewares._session_context import get_active_resolved_tools
from myrm_agent_harness.agent.skill_agent import SkillAgent
from myrm_agent_harness.agent.skills.runtime.skill_catalog_delivery import (
    build_bound_skills_block,
)
from myrm_agent_harness.backends.skills.types import SkillMetadata

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

_APPEND = TurnHistory(mode="append")


class _MutableSkillBackend:
    """Minimal skill backend with hot-reloadable skill list."""

    def __init__(self, skills: list[SkillMetadata]) -> None:
        self._skills = list(skills)

    async def list_skills(self) -> list[SkillMetadata]:
        return list(self._skills)

    async def load_skills(self, skill_ids: list[str]) -> list[SkillMetadata]:
        by_name = {skill.name: skill for skill in self._skills}
        return [by_name[skill_id] for skill_id in skill_ids if skill_id in by_name]


def _build_checkpoint_graph() -> CompiledStateGraph:
    """Minimal LangGraph with MemorySaver for real aget_state / aupdate_state."""

    def passthrough(state: MessagesState) -> MessagesState:
        return state

    builder = StateGraph(MessagesState)
    builder.add_node("pass", passthrough)
    builder.add_edge(START, "pass")
    return builder.compile(checkpointer=MemorySaver())


def _skill(name: str, description: str) -> SkillMetadata:
    return SkillMetadata(
        name=name,
        description=description,
        model_invocable=True,
        available=True,
    )


def _many_skills(count: int, *, prefix: str = "bound") -> list[SkillMetadata]:
    return [_skill(f"{prefix}_{index:02d}_skill", f"desc {index}") for index in range(count)]


def _skills_for_search_mount(*, featured: SkillMetadata) -> list[SkillMetadata]:
    skills = _many_skills(21)
    featured_inline = SkillMetadata(
        name=featured.name,
        description=featured.description,
        model_invocable=featured.model_invocable,
        available=featured.available,
        always=True,
    )
    skills[0] = featured_inline
    return skills


def _agent_with_search_mounted(skills: list[SkillMetadata]) -> tuple[SkillAgent, _MutableSkillBackend]:
    backend = _MutableSkillBackend(skills)
    agent = SkillAgent(llm=AsyncMock(), skill_backend=backend)
    sync_discover_capability_tool(agent._tool_registry, skills=backend._skills)
    return agent, backend


async def _search(tools: list, query: str) -> str:
    search_tool = next((tool for tool in tools if tool.name == "skill_search_tool"), None)
    assert search_tool is not None
    result = await search_tool.ainvoke({"query": query})
    assert isinstance(result, str)
    return result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resume_leaves_the_checkpoint_messages_alone_even_when_the_bind_list_drifted() -> None:
    """A drift during the pause reaches the model on the next message; the baseline is never rewritten."""
    old_skill = _skill("legacy_skill", "legacy")
    new_skill = _skill("current_skill", "current")
    stale_block = build_bound_skills_block([old_skill])
    graph = _build_checkpoint_graph()
    thread_id = "integration-resume-catalog-untouched"
    config = {"configurable": {"thread_id": thread_id}}
    await graph.aupdate_state(config, {"messages": [HumanMessage(content=f"{stale_block}\n\napproval pending")]})

    agent = SkillAgent(llm=AsyncMock(), skill_backend=_MutableSkillBackend([new_skill]))
    agent._agent = graph

    await sync_bound_skills_for_resume(agent)

    snapshot = await graph.aget_state(config)
    assert snapshot.values["messages"][0].content == f"{stale_block}\n\napproval pending"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_the_next_message_after_a_resume_delivers_the_drift_as_an_update() -> None:
    old_skill = _skill("legacy_skill", "legacy")
    new_skill = _skill("current_skill", "current")
    graph = _build_checkpoint_graph()
    thread_id = "integration-resume-then-update"
    config = {"configurable": {"thread_id": thread_id}}
    await graph.aupdate_state(
        config, {"messages": [HumanMessage(content=f"{build_bound_skills_block([old_skill])}\n\nfirst")]}
    )
    agent = SkillAgent(llm=AsyncMock(), skill_backend=_MutableSkillBackend([new_skill]))
    await sync_bound_skills_for_resume(agent)
    thread_messages = tuple((await graph.aget_state(config)).values["messages"])

    new_turn = [HumanMessage(content="second")]
    delivery = await deliver_bound_skills_catalog(
        new_turn, agent, TurnHistory(mode="continue", thread_messages=thread_messages)
    )

    assert delivery.action == "update"
    content = new_turn[0].content
    assert isinstance(content, str)
    assert content.startswith("<bound_skills_update")
    assert "current_skill" in content
    assert "legacy_skill" not in content
    assert content.endswith("second")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stream_baseline_honors_desired_skill_ids_from_backend() -> None:
    """Baseline prep uses load_skills when desired_skill_ids is set."""
    visible = _skill("visible_skill", "visible")
    hidden = _skill("hidden_skill", "hidden")
    agent = SkillAgent(llm=AsyncMock(), skill_backend=_MutableSkillBackend([visible, hidden]))
    agent._desired_skill_ids = ["visible_skill"]

    messages = [HumanMessage(content="approve tool use")]
    await deliver_bound_skills_catalog(messages, agent, _APPEND)

    first_content = messages[0].content
    assert isinstance(first_content, str)
    assert "visible_skill" in first_content
    assert "hidden_skill" not in first_content


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resume_syncs_skill_search_index_when_bind_changes() -> None:
    """skill_search_tool index matches the refreshed bind list after resume prep."""
    old_skill = _skill("legacy_search_skill", "legacy")
    new_skill = _skill("fresh_search_skill", "fresh")
    agent, backend = _agent_with_search_mounted(_skills_for_search_mount(featured=old_skill))

    backend._skills = _skills_for_search_mount(featured=new_skill)
    await sync_bound_skills_for_resume(agent)

    assert agent._cached_tools is not None
    result = await _search(agent._cached_tools, "*")
    assert "fresh_search_skill" in result
    assert "legacy_search_skill" not in result

    active_tools = get_active_resolved_tools()
    assert active_tools is not None
    assert "fresh_search_skill" in await _search(active_tools, "*")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stream_syncs_skill_search_index_when_bind_changes() -> None:
    """New-message stream prep syncs skill_search_tool when the bind list drifts."""
    old_skill = _skill("legacy_stream_skill", "legacy")
    new_skill = _skill("fresh_stream_skill", "fresh")
    agent, backend = _agent_with_search_mounted(_skills_for_search_mount(featured=old_skill))

    messages = [HumanMessage(content="follow-up question")]
    backend._skills = _skills_for_search_mount(featured=new_skill)
    delivery = await deliver_bound_skills_catalog(messages, agent, _APPEND)

    first_content = messages[0].content
    assert isinstance(first_content, str)
    assert "fresh_stream_skill" in first_content
    assert "legacy_stream_skill" not in first_content
    assert delivery.action == "baseline"

    assert agent._cached_tools is not None
    result = await _search(agent._cached_tools, "*")
    assert "fresh_stream_skill" in result
    assert "legacy_stream_skill" not in result

    active_tools = get_active_resolved_tools()
    assert active_tools is not None
    assert "fresh_stream_skill" in await _search(active_tools, "*")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resume_removes_skill_search_when_all_skills_unbound() -> None:
    """Unbinding every skill removes the stale skill_search_tool at resume prep."""
    agent, backend = _agent_with_search_mounted(
        _skills_for_search_mount(featured=_skill("legacy_unbind_skill", "legacy"))
    )

    backend._skills = []
    await sync_bound_skills_for_resume(agent)

    assert agent._cached_tools is not None
    assert not any(tool.name == "skill_search_tool" for tool in agent._cached_tools)

    active_tools = get_active_resolved_tools()
    assert active_tools is not None
    assert not any(tool.name == "skill_search_tool" for tool in active_tools)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stream_removes_skill_search_when_all_skills_unbound() -> None:
    """New-message stream prep removes skill_search_tool when the bind list becomes empty."""
    agent, backend = _agent_with_search_mounted(
        _skills_for_search_mount(featured=_skill("legacy_stream_unbind_skill", "legacy"))
    )

    messages = [HumanMessage(content="follow-up question")]
    backend._skills = []
    await deliver_bound_skills_catalog(messages, agent, _APPEND)

    first_content = messages[0].content
    assert isinstance(first_content, str)
    assert "<bound_skills" not in first_content

    assert agent._cached_tools is not None
    assert not any(tool.name == "skill_search_tool" for tool in agent._cached_tools)

    active_tools = get_active_resolved_tools()
    assert active_tools is not None
    assert not any(tool.name == "skill_search_tool" for tool in active_tools)
