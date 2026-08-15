"""Unit tests for the memory_search_tool skill-usage guard."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.errors.tool_error_category import ToolErrorCategory
from myrm_agent_harness.agent.skill_agent.context import (
    reset_loaded_skills,
    set_loaded_skills,
)
from myrm_agent_harness.backends.skills.types_metadata import SkillMetadata
from myrm_agent_harness.toolkits.memory.agent_surface.skill_usage_guard import (
    build_skill_usage_guide,
    detect_against_loaded,
    detect_skill_usage_lookup,
    extract_skill_core_terms,
)
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.utils.errors import ToolError

_MCP_SKILL = SkillMetadata(name="mcp_12306_skill", description="12306 ticket queries")


def test_extract_skill_core_terms_mcp_12306() -> None:
    terms = extract_skill_core_terms("mcp_12306_skill")
    assert "12306" in terms
    assert "mcp_12306_skill" in terms
    assert "12306_skill" in terms
    assert "12306 skill" in terms


def test_extract_skill_core_terms_web_research() -> None:
    terms = extract_skill_core_terms("web_research_skill")
    assert "web_research" in terms
    assert "web research" in terms


def test_detect_hits_zh_usage_query() -> None:
    hit = detect_against_loaded("12306 查询 北京 上海 高铁", [_MCP_SKILL])
    assert hit is not None
    assert hit.skill_name == "mcp_12306_skill"
    assert hit.matched_term == "12306"


def test_detect_hits_en_usage_query() -> None:
    hit = detect_against_loaded("how to use the 12306 skill", [_MCP_SKILL])
    assert hit is not None
    assert hit.skill_name == "mcp_12306_skill"


def test_detect_hits_how_to_use() -> None:
    hit = detect_against_loaded("12306 怎么用", [_MCP_SKILL])
    assert hit is not None


def test_detect_ignores_preference_recall() -> None:
    assert detect_against_loaded("12306 的使用偏好", [_MCP_SKILL]) is None


def test_detect_ignores_history_recall() -> None:
    assert detect_against_loaded("上次买的12306车票还在吗", [_MCP_SKILL]) is None


def test_detect_ignores_unrelated_query() -> None:
    assert detect_against_loaded("user's travel preferences", [_MCP_SKILL]) is None


def test_detect_ignores_empty_loaded_skills() -> None:
    assert detect_against_loaded("12306 查询 北京 上海 高铁", []) is None


def test_detect_ignores_empty_query() -> None:
    assert detect_against_loaded("", [_MCP_SKILL]) is None


def test_detect_uses_context_var_loaded_skills() -> None:
    reset_loaded_skills()
    try:
        assert detect_skill_usage_lookup("12306 查询 北京 上海 高铁") is None
        set_loaded_skills([_MCP_SKILL])
        hit = detect_skill_usage_lookup("12306 查询 北京 上海 高铁")
        assert hit is not None
        assert hit.skill_name == "mcp_12306_skill"
    finally:
        reset_loaded_skills()


def test_build_skill_usage_guide_mentions_redirect() -> None:
    hit = detect_against_loaded("12306 查询 北京 上海 高铁", [_MCP_SKILL])
    assert hit is not None
    guide = build_skill_usage_guide(hit)
    assert "mcp_12306_skill" in guide
    assert "file_read_tool" in guide
    assert "bash PTC" in guide
    assert "memory_search_tool" in guide


@pytest.mark.asyncio
async def test_memory_search_intercepted_when_skill_loaded(
    mock_vector_store, mock_embedding, memory_config
) -> None:
    manager = MemoryManager(
        memory_config,
        user_id="test_user",
        vector=mock_vector_store,
        embedding=mock_embedding,
    )
    from myrm_agent_harness.toolkits.memory.memory_agent_tools import (
        create_memory_tools,
    )

    search_tool = next(
        tool for tool in create_memory_tools(manager) if tool.name == "memory_search_tool"
    )
    reset_loaded_skills()
    try:
        set_loaded_skills([_MCP_SKILL])
        with pytest.raises(ToolError) as exc_info:
            await search_tool.ainvoke({"query": "12306 查询 北京 上海 高铁"})
        assert exc_info.value.error_category == ToolErrorCategory.SKILL_USAGE_GUARD.value
        assert exc_info.value.error_code == "SKILL_USAGE_LOOKUP_BLOCKED"
    finally:
        reset_loaded_skills()


@pytest.mark.asyncio
async def test_memory_search_runs_when_no_skill_loaded(
    mock_vector_store, mock_embedding, memory_config
) -> None:
    manager = MemoryManager(
        memory_config,
        user_id="test_user",
        vector=mock_vector_store,
        embedding=mock_embedding,
    )
    from myrm_agent_harness.toolkits.memory.memory_agent_tools import (
        create_memory_tools,
    )

    search_tool = next(
        tool for tool in create_memory_tools(manager) if tool.name == "memory_search_tool"
    )
    reset_loaded_skills()
    try:
        result = await search_tool.ainvoke({"query": "12306 查询 北京 上海 高铁"})
        assert isinstance(result, str)
    finally:
        reset_loaded_skills()


@pytest.mark.asyncio
async def test_guard_error_reaches_tool_message_error_category() -> None:
    """The ToolError raised by the guard must surface error_category on the
    ToolMessage produced by the execution-error handler (same contract as
    BENCHMARK_BLOCKED) so SSE/Goodhart can distinguish a controlled redirect
    from a real misuse."""
    from unittest.mock import AsyncMock, patch

    from myrm_agent_harness.agent.middlewares.tooling._tool_execution_lifecycle import (
        handle_execution_error,
    )
    from myrm_agent_harness.toolkits.memory.agent_surface.skill_usage_guard import (
        SkillUsageHit,
        build_skill_usage_guide,
    )

    hit = SkillUsageHit(skill_name="mcp_12306_skill", matched_term="12306")
    error = ToolError(
        build_skill_usage_guide(hit),
        user_hint="Skill usage instructions live in the loaded skill SOP.",
        error_code="SKILL_USAGE_LOOKUP_BLOCKED",
        diagnostic_info={
            "error_category": ToolErrorCategory.SKILL_USAGE_GUARD.value,
            "skill_name": hit.skill_name,
            "matched_term": hit.matched_term,
        },
    )
    with patch(
        "myrm_agent_harness.agent.hooks.executor.fire_hook",
        new_callable=AsyncMock,
    ):
        message = await handle_execution_error(
            error,
            "memory_search_tool",
            "call_guard_1",
            {"query": "12306 查询 北京 上海 高铁"},
        )
    assert message.status == "error"
    assert (
        message.additional_kwargs.get("error_category")
        == ToolErrorCategory.SKILL_USAGE_GUARD.value
    )
    assert "file_read_tool" in str(message.content)
