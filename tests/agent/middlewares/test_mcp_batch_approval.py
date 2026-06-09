"""Tests for MCP Fast-Path Auto-Approve in batch_processor (non-PTC path).

Verifies that direct MCP tool calls (not via bash_code_execute_tool/PTC)
are auto-approved when their registered annotations indicate readOnly and
not openWorld, and remain in pending_approval otherwise.
"""

from unittest.mock import patch

import pytest
from langchain_core.messages import ToolCall

from myrm_agent_harness.agent.middlewares.approval.batch_processor import evaluate_tool_batch
from myrm_agent_harness.agent.security.tool_registry import SafetyMetadata
from myrm_agent_harness.agent.security.types import (
    PathPolicy,
    PermissionAction,
    PermissionRule,
    SecurityConfig,
)


@pytest.mark.asyncio
async def test_mcp_readonly_tool_auto_approved():
    """Read-only MCP tool with registered annotations gets Fast-Path auto-approve."""
    with patch(
        "myrm_agent_harness.agent.middlewares.approval.batch_processor.resolve_safety_metadata"
    ) as mock_meta:
        mock_meta.return_value = SafetyMetadata(
            is_read_only=True, is_open_world=False, is_concurrent_safe=True
        )

        config = SecurityConfig(auto_mode_enabled=False, path_policy=PathPolicy())
        tool_call = ToolCall(
            name="mcp__gmail__search_inbox",
            args={"query": "from:zhang@example.com"},
            id="call_read",
        )

        auto_approved, auto_denied, pending = await evaluate_tool_batch(
            tool_calls=[tool_call],
            config=config,
            is_cron=False,
            workspace_root="/workspace",
            session_key="test_sess",
            args_hashes={},
        )

        assert len(auto_approved) == 1
        assert len(auto_denied) == 0
        assert len(pending) == 0
        assert auto_approved[0][1].get("id") == "call_read"
        mock_meta.assert_called_once_with("mcp__gmail__search_inbox")


@pytest.mark.asyncio
async def test_mcp_writable_tool_stays_pending():
    """Non-read-only MCP tool stays in pending_approval (HITL prompt)."""
    with patch(
        "myrm_agent_harness.agent.middlewares.approval.batch_processor.resolve_safety_metadata"
    ) as mock_meta:
        mock_meta.return_value = SafetyMetadata(
            is_read_only=False, is_open_world=False, is_destructive=True
        )

        config = SecurityConfig(auto_mode_enabled=False, path_policy=PathPolicy())
        tool_call = ToolCall(
            name="mcp__gmail__send_email",
            args={"to": "bob@example.com", "subject": "Hi"},
            id="call_write",
        )

        auto_approved, auto_denied, pending = await evaluate_tool_batch(
            tool_calls=[tool_call],
            config=config,
            is_cron=False,
            workspace_root="/workspace",
            session_key="test_sess",
            args_hashes={},
        )

        assert len(auto_approved) == 0
        assert len(auto_denied) == 0
        assert len(pending) == 1


@pytest.mark.asyncio
async def test_mcp_readonly_but_open_world_stays_pending():
    """Read-only but openWorld MCP tool stays in pending_approval."""
    with patch(
        "myrm_agent_harness.agent.middlewares.approval.batch_processor.resolve_safety_metadata"
    ) as mock_meta:
        mock_meta.return_value = SafetyMetadata(
            is_read_only=True, is_open_world=True, is_concurrent_safe=True
        )

        config = SecurityConfig(auto_mode_enabled=False, path_policy=PathPolicy())
        tool_call = ToolCall(
            name="mcp__web_scraper__fetch_page",
            args={"url": "https://example.com"},
            id="call_open_world",
        )

        auto_approved, auto_denied, pending = await evaluate_tool_batch(
            tool_calls=[tool_call],
            config=config,
            is_cron=False,
            workspace_root="/workspace",
            session_key="test_sess",
            args_hashes={},
        )

        assert len(auto_approved) == 0
        assert len(auto_denied) == 0
        assert len(pending) == 1


@pytest.mark.asyncio
async def test_mcp_unknown_tool_stays_pending():
    """MCP tool with no registered annotations stays in pending (fail-closed)."""
    config = SecurityConfig(auto_mode_enabled=False, path_policy=PathPolicy())
    tool_call = ToolCall(
        name="mcp__unknown_server__mystery_tool",
        args={},
        id="call_unknown",
    )

    auto_approved, auto_denied, pending = await evaluate_tool_batch(
        tool_calls=[tool_call],
        config=config,
        is_cron=False,
        workspace_root="/workspace",
        session_key="test_sess",
        args_hashes={},
    )

    assert len(auto_approved) == 0
    assert len(auto_denied) == 0
    assert len(pending) == 1


@pytest.mark.asyncio
async def test_mcp_denied_by_rule_not_overridden():
    """Per-tool DENY rule is respected — Fast-Path cannot override DENY."""
    ruleset = (PermissionRule("mcp_invoke", "mcp__gmail__*", PermissionAction.DENY),)
    config = SecurityConfig(auto_mode_enabled=False, path_policy=PathPolicy(), ruleset=ruleset)
    tool_call = ToolCall(
        name="mcp__gmail__search_inbox",
        args={"query": "test"},
        id="call_denied",
    )

    auto_approved, auto_denied, pending = await evaluate_tool_batch(
        tool_calls=[tool_call],
        config=config,
        is_cron=False,
        workspace_root="/workspace",
        session_key="test_sess",
        args_hashes={},
    )

    assert len(auto_approved) == 0
    assert len(auto_denied) == 1
    assert len(pending) == 0


@pytest.mark.asyncio
async def test_mcp_mixed_batch_readonly_and_writable():
    """Mixed batch: read-only tool auto-approved, writable tool stays pending."""
    with patch(
        "myrm_agent_harness.agent.middlewares.approval.batch_processor.resolve_safety_metadata"
    ) as mock_meta:
        def side_effect(name):
            if name == "mcp__gmail__search_inbox":
                return SafetyMetadata(is_read_only=True, is_open_world=False, is_concurrent_safe=True)
            return SafetyMetadata()

        mock_meta.side_effect = side_effect

        config = SecurityConfig(auto_mode_enabled=False, path_policy=PathPolicy())
        tool_calls = [
            ToolCall(name="mcp__gmail__search_inbox", args={"query": "test"}, id="call_read"),
            ToolCall(name="mcp__gmail__send_email", args={"to": "a@b.com"}, id="call_write"),
        ]

        auto_approved, auto_denied, pending = await evaluate_tool_batch(
            tool_calls=tool_calls,
            config=config,
            is_cron=False,
            workspace_root="/workspace",
            session_key="test_sess",
            args_hashes={},
        )

        assert len(auto_approved) == 1
        assert auto_approved[0][1].get("id") == "call_read"
        assert len(auto_denied) == 0
        assert len(pending) == 1
        assert pending[0][1].get("id") == "call_write"


@pytest.mark.asyncio
async def test_mcp_readonly_but_destructive_stays_pending():
    """Contradictory annotations (readOnly + destructive) stay pending (defensive)."""
    with patch(
        "myrm_agent_harness.agent.middlewares.approval.batch_processor.resolve_safety_metadata"
    ) as mock_meta:
        mock_meta.return_value = SafetyMetadata(
            is_read_only=True, is_destructive=True, is_open_world=False, is_concurrent_safe=True
        )

        config = SecurityConfig(auto_mode_enabled=False, path_policy=PathPolicy())
        tool_call = ToolCall(
            name="mcp__buggy_server__contradictory_tool",
            args={},
            id="call_contradictory",
        )

        auto_approved, auto_denied, pending = await evaluate_tool_batch(
            tool_calls=[tool_call],
            config=config,
            is_cron=False,
            workspace_root="/workspace",
            session_key="test_sess",
            args_hashes={},
        )

        assert len(auto_approved) == 0
        assert len(auto_denied) == 0
        assert len(pending) == 1
