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
    refreshed = await apply_bound_skill_catalog_for_resume(
        agent, command, thread_id=thread_id
    )

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
    refreshed = await apply_bound_skill_catalog_for_resume(
        agent, command, thread_id="missing-thread-id"
    )
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
    refreshed = await apply_bound_skill_catalog_for_resume(
        agent, command, thread_id=thread_id
    )
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
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
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
