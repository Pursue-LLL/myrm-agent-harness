"""Integration tests for resume-path bound skill catalog refresh (real checkpoint, no mock aget_state)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.types import Command

from myrm_agent_harness.agent._internals.agent_runtime import (
    apply_bound_skill_catalog_for_resume,
    apply_bound_skill_catalog_for_stream,
)
from myrm_agent_harness.agent.skill_agent import SkillAgent
from myrm_agent_harness.agent.skills.runtime.skill_catalog_delivery import (
    build_bound_skills_block,
)
from myrm_agent_harness.backends.skills.types import SkillMetadata

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph


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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resume_refreshes_stale_catalog_from_real_checkpoint() -> None:
    """Hot-reloaded skills appear in checkpoint HumanMessage after resume prep."""
    old_skill = _skill("legacy_skill", "legacy")
    new_skill = _skill("current_skill", "current")
    stale_block = build_bound_skills_block([old_skill])

    graph = _build_checkpoint_graph()
    thread_id = "integration-resume-catalog-refresh"
    config = {"configurable": {"thread_id": thread_id}}
    await graph.aupdate_state(
        config,
        {"messages": [HumanMessage(content=f"{stale_block}\n\napproval pending")]},
    )

    backend = _MutableSkillBackend([new_skill])
    agent = SkillAgent(llm=AsyncMock(), skill_backend=backend)
    agent._agent = graph

    command = Command(resume={"decision": "approve"})
    refreshed = await apply_bound_skill_catalog_for_resume(agent, command, thread_id=thread_id)

    assert refreshed is not command
    updated_messages = refreshed.update.get("messages")
    assert isinstance(updated_messages, list)
    first_content = updated_messages[0].content
    assert isinstance(first_content, str)
    assert "current_skill" in first_content
    assert "legacy_skill" not in first_content

    snapshot = await graph.aget_state(config)
    assert snapshot.values is not None
    checkpoint_content = snapshot.values["messages"][0].content
    assert isinstance(checkpoint_content, str)
    assert "legacy_skill" in checkpoint_content


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resume_no_op_when_checkpoint_thread_missing() -> None:
    """Real aget_state on empty thread returns original Command unchanged."""
    graph = _build_checkpoint_graph()
    backend = _MutableSkillBackend([_skill("alpha_skill", "alpha")])
    agent = SkillAgent(llm=AsyncMock(), skill_backend=backend)
    agent._agent = graph

    command = Command(resume={"decision": "approve"})
    refreshed = await apply_bound_skill_catalog_for_resume(agent, command, thread_id="missing-thread-id")
    assert refreshed is command
    assert refreshed.update is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resume_no_op_when_catalog_already_matches_bind_list() -> None:
    """Real checkpoint with current catalog does not emit Command.update."""
    skill = _skill("aligned_skill", "aligned")
    block = build_bound_skills_block([skill])

    graph = _build_checkpoint_graph()
    thread_id = "integration-resume-catalog-aligned"
    config = {"configurable": {"thread_id": thread_id}}
    await graph.aupdate_state(
        config,
        {"messages": [HumanMessage(content=f"{block}\n\nquestion")]},
    )

    backend = _MutableSkillBackend([skill])
    agent = SkillAgent(llm=AsyncMock(), skill_backend=backend)
    agent._agent = graph

    command = Command(resume="continue")
    refreshed = await apply_bound_skill_catalog_for_resume(agent, command, thread_id=thread_id)
    assert refreshed is command


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resume_refreshes_multimodal_checkpoint_content() -> None:
    """Real checkpoint with list HumanMessage content gets catalog refresh."""
    old_skill = _skill("old_mm_skill", "old")
    new_skill = _skill("new_mm_skill", "new")
    stale_block = build_bound_skills_block([old_skill])

    graph = _build_checkpoint_graph()
    thread_id = "integration-resume-catalog-multimodal"
    config = {"configurable": {"thread_id": thread_id}}
    await graph.aupdate_state(
        config,
        {
            "messages": [
                HumanMessage(
                    content=[
                        {"type": "text", "text": f"{stale_block}\n\nquestion"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64,abc"},
                        },
                    ]
                )
            ]
        },
    )

    backend = _MutableSkillBackend([new_skill])
    agent = SkillAgent(llm=AsyncMock(), skill_backend=backend)
    agent._agent = graph

    refreshed = await apply_bound_skill_catalog_for_resume(
        agent, Command(resume={"decision": "approve"}), thread_id=thread_id
    )

    assert refreshed.update is not None
    first_content = refreshed.update["messages"][0].content
    assert isinstance(first_content, list)
    text_part = next(part for part in first_content if part.get("type") == "text")
    assert "new_mm_skill" in text_part["text"]
    assert "old_mm_skill" not in text_part["text"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resume_honors_desired_skill_ids_from_backend() -> None:
    """Real checkpoint refresh uses load_skills when desired_skill_ids is set."""
    visible = _skill("visible_skill", "visible")
    hidden = _skill("hidden_skill", "hidden")
    stale_block = build_bound_skills_block([hidden])

    graph = _build_checkpoint_graph()
    thread_id = "integration-resume-desired-ids"
    config = {"configurable": {"thread_id": thread_id}}
    await graph.aupdate_state(
        config,
        {"messages": [HumanMessage(content=f"{stale_block}\n\napprove tool use")]},
    )

    backend = _MutableSkillBackend([visible, hidden])
    agent = SkillAgent(llm=AsyncMock(), skill_backend=backend)
    agent._desired_skill_ids = ["visible_skill"]
    agent._agent = graph

    refreshed = await apply_bound_skill_catalog_for_resume(
        agent, Command(resume={"decision": "approve"}), thread_id=thread_id
    )

    assert refreshed.update is not None
    first_content = refreshed.update["messages"][0].content
    assert isinstance(first_content, str)
    assert "visible_skill" in first_content
    assert "hidden_skill" not in first_content


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resume_syncs_skill_search_index_when_bind_changes() -> None:
    """skill_search_tool index matches refreshed bind list after resume catalog update."""
    old_skill = _skill("legacy_search_skill", "legacy")
    new_skill = _skill("fresh_search_skill", "fresh")
    stale_block = build_bound_skills_block([old_skill], hidden_skill_count=1)

    graph = _build_checkpoint_graph()
    thread_id = "integration-resume-search-sync"
    config = {"configurable": {"thread_id": thread_id}}
    await graph.aupdate_state(
        config,
        {"messages": [HumanMessage(content=f"{stale_block}\n\napproval pending")]},
    )

    backend = _MutableSkillBackend(_skills_for_search_mount(featured=old_skill))
    agent = SkillAgent(llm=AsyncMock(), skill_backend=backend)
    agent._agent = graph

    from myrm_agent_harness.agent.meta_tools.discover_capability.discover_capability_tool import (
        sync_discover_capability_tool,
    )

    sync_discover_capability_tool(agent._tool_registry, skills=backend._skills)

    backend._skills = _skills_for_search_mount(featured=new_skill)
    refreshed = await apply_bound_skill_catalog_for_resume(
        agent, Command(resume={"decision": "approve"}), thread_id=thread_id
    )
    assert refreshed.update is not None

    assert agent._cached_tools is not None
    search_tool = next(
        (tool for tool in agent._cached_tools if tool.name == "skill_search_tool"),
        None,
    )
    assert search_tool is not None

    result = await search_tool.ainvoke({"query": "*"})
    assert isinstance(result, str)
    assert "fresh_search_skill" in result
    assert "legacy_search_skill" not in result

    from myrm_agent_harness.agent.middlewares._session_context import (
        get_active_resolved_tools,
    )

    active_tools = get_active_resolved_tools()
    assert active_tools is not None
    active_search = next(
        (tool for tool in active_tools if tool.name == "skill_search_tool"),
        None,
    )
    assert active_search is not None
    active_result = await active_search.ainvoke({"query": "*"})
    assert isinstance(active_result, str)
    assert "fresh_search_skill" in active_result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stream_syncs_skill_search_index_when_bind_changes() -> None:
    """New-message stream prep syncs skill_search_tool when bind list drifts."""
    old_skill = _skill("legacy_stream_skill", "legacy")
    new_skill = _skill("fresh_stream_skill", "fresh")
    stale_block = build_bound_skills_block([old_skill], hidden_skill_count=1)

    backend = _MutableSkillBackend(_skills_for_search_mount(featured=old_skill))
    agent = SkillAgent(llm=AsyncMock(), skill_backend=backend)

    from myrm_agent_harness.agent.meta_tools.discover_capability.discover_capability_tool import (
        sync_discover_capability_tool,
    )

    sync_discover_capability_tool(agent._tool_registry, skills=backend._skills)

    messages = [HumanMessage(content=f"{stale_block}\n\nfollow-up question")]
    backend._skills = _skills_for_search_mount(featured=new_skill)
    catalog_changed = await apply_bound_skill_catalog_for_stream(messages, agent)
    assert catalog_changed is True

    first_content = messages[0].content
    assert isinstance(first_content, str)
    assert "fresh_stream_skill" in first_content
    assert "legacy_stream_skill" not in first_content

    assert agent._cached_tools is not None
    search_tool = next(
        (tool for tool in agent._cached_tools if tool.name == "skill_search_tool"),
        None,
    )
    assert search_tool is not None

    result = await search_tool.ainvoke({"query": "*"})
    assert isinstance(result, str)
    assert "fresh_stream_skill" in result
    assert "legacy_stream_skill" not in result

    from myrm_agent_harness.agent.middlewares._session_context import (
        get_active_resolved_tools,
    )

    active_tools = get_active_resolved_tools()
    assert active_tools is not None
    active_search = next(
        (tool for tool in active_tools if tool.name == "skill_search_tool"),
        None,
    )
    assert active_search is not None
    active_result = await active_search.ainvoke({"query": "*"})
    assert isinstance(active_result, str)
    assert "fresh_stream_skill" in active_result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resume_removes_skill_search_when_all_skills_unbound() -> None:
    """Unbinding every skill removes stale skill_search_tool after resume catalog refresh."""
    old_skill = _skill("legacy_unbind_skill", "legacy")
    stale_block = build_bound_skills_block([old_skill], hidden_skill_count=1)

    graph = _build_checkpoint_graph()
    thread_id = "integration-resume-empty-bind"
    config = {"configurable": {"thread_id": thread_id}}
    await graph.aupdate_state(
        config,
        {"messages": [HumanMessage(content=f"{stale_block}\n\napproval pending")]},
    )

    backend = _MutableSkillBackend(_skills_for_search_mount(featured=old_skill))
    agent = SkillAgent(llm=AsyncMock(), skill_backend=backend)
    agent._agent = graph

    from myrm_agent_harness.agent.meta_tools.discover_capability.discover_capability_tool import (
        sync_discover_capability_tool,
    )

    sync_discover_capability_tool(agent._tool_registry, skills=backend._skills)

    backend._skills = []
    refreshed = await apply_bound_skill_catalog_for_resume(
        agent, Command(resume={"decision": "approve"}), thread_id=thread_id
    )
    assert refreshed.update is not None

    first_content = refreshed.update["messages"][0].content
    assert isinstance(first_content, str)
    assert "<bound_skills" not in first_content

    assert agent._cached_tools is not None
    assert not any(tool.name == "skill_search_tool" for tool in agent._cached_tools)

    from myrm_agent_harness.agent.middlewares._session_context import (
        get_active_resolved_tools,
    )

    active_tools = get_active_resolved_tools()
    assert active_tools is not None
    assert not any(tool.name == "skill_search_tool" for tool in active_tools)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stream_removes_skill_search_when_all_skills_unbound() -> None:
    """New-message stream prep removes skill_search_tool when bind list becomes empty."""
    old_skill = _skill("legacy_stream_unbind_skill", "legacy")
    stale_block = build_bound_skills_block([old_skill], hidden_skill_count=1)

    backend = _MutableSkillBackend(_skills_for_search_mount(featured=old_skill))
    agent = SkillAgent(llm=AsyncMock(), skill_backend=backend)

    from myrm_agent_harness.agent.meta_tools.discover_capability.discover_capability_tool import (
        sync_discover_capability_tool,
    )

    sync_discover_capability_tool(agent._tool_registry, skills=backend._skills)

    messages = [HumanMessage(content=f"{stale_block}\n\nfollow-up question")]
    backend._skills = []
    catalog_changed = await apply_bound_skill_catalog_for_stream(messages, agent)
    assert catalog_changed is True

    first_content = messages[0].content
    assert isinstance(first_content, str)
    assert "<bound_skills" not in first_content

    assert agent._cached_tools is not None
    assert not any(tool.name == "skill_search_tool" for tool in agent._cached_tools)
