"""Tests for deferred tool hit formatting."""

from __future__ import annotations

from myrm_agent_harness.agent.tool_management.defer.activation import (
    format_deferred_tool_hit,
)


def test_format_deferred_tool_hit() -> None:
    line = format_deferred_tool_hit("cron_manage_tool", {"type": "object"})
    assert 'name="cron_manage_tool"' in line
    assert "schema_hint=" in line
    assert line.startswith("<DeferredToolHit ")
    assert line.endswith("/>")
