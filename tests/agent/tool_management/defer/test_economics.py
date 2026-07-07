"""Tests for DeferEconomics gateway binding rules."""

from __future__ import annotations

from langchain.tools import tool

from myrm_agent_harness.agent.tool_management.defer.economics import (
    LARGE_DEFER_TOOL_SCHEMA_TOKENS,
    should_bind_discover_gateway,
)


@tool("small_defer_tool", description="x" * 80)
def _small_tool() -> str:
    return "ok"


@tool("cron_manage_tool", description="x" * 2000)
def _large_tool() -> str:
    return "ok"


def test_economics_binds_when_searchable_skills() -> None:
    assert should_bind_discover_gateway(1, []) is True


def test_economics_skips_default_small_pool() -> None:
    tools = [_small_tool, _small_tool]
    assert should_bind_discover_gateway(0, tools) is False


def test_economics_binds_when_more_than_two_deferred() -> None:
    tools = [_small_tool, _small_tool, _small_tool]
    assert should_bind_discover_gateway(0, tools) is True


def test_economics_binds_when_single_large_defer_tool() -> None:
    assert should_bind_discover_gateway(0, [_large_tool]) is True
    assert LARGE_DEFER_TOOL_SCHEMA_TOKENS == 400
