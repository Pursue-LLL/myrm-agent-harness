"""Tests for deferred tool hit parsing."""

from __future__ import annotations

from myrm_agent_harness.agent.tool_management.defer.activation import (
    format_deferred_tool_hit,
    parse_deferred_tool_hits,
)


def test_parse_deferred_tool_hits() -> None:
    content = (
        "<DeferredToolHits>\n"
        + format_deferred_tool_hit("cron_manage_tool", {"type": "object"})
        + "\n</DeferredToolHits>"
    )
    assert parse_deferred_tool_hits(content) == {"cron_manage_tool"}


def test_is_discover_capability_tool_message() -> None:
    from myrm_agent_harness.agent.tool_management.defer.activation import (
        is_discover_capability_tool_message,
    )

    assert is_discover_capability_tool_message("discover_capability_tool")
    assert is_discover_capability_tool_message("discover_capability")
    assert not is_discover_capability_tool_message("bash_tool")
    assert not is_discover_capability_tool_message(None)
