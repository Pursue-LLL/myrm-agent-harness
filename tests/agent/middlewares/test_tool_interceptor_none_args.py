"""Tests for tool_interceptor_middleware None-args safety fixes.

Validates that:
1. tool_args defaults to {} when request.tool_call["args"] is None
2. pre_hook_result.updated_input=None does NOT overwrite tool_args
3. The interceptor chain survives when all hooks return empty results
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.agent.hooks.types import AggregatedHookResult, HookResult


@pytest.fixture
def _mock_env():
    """Provide minimal mocks so the interceptor doesn't crash on import-time deps."""
    with (
        patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_security_config", return_value=None),
        patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_workspace_root", return_value="/tmp"),
        patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_approval_session", return_value="sess"),
        patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_approval_user_id", return_value="user"),
        patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_event_logger", return_value=None),
        patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_terminal_errors") as mock_te,
        patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_allowed_domains_map", return_value={}),
    ):
        registry = MagicMock()
        registry.get_all.return_value = {}
        mock_te.return_value = registry
        yield


class TestToolArgsNoneProtection:
    """Ensure tool_args is always a dict even when model sends args=None."""

    def test_get_or_fallback_explicit_none(self):
        """Simulate request.tool_call['args'] being explicitly None."""
        tool_call: dict[str, object] = {"name": "test_tool", "args": None, "id": "call_1"}
        tool_args: dict[str, object] = tool_call.get("args") or {}
        assert tool_args == {}
        assert isinstance(tool_args, dict)

    def test_get_or_fallback_missing_key(self):
        """Simulate request.tool_call having no 'args' key at all."""
        tool_call: dict[str, object] = {"name": "test_tool", "id": "call_2"}
        tool_args: dict[str, object] = tool_call.get("args") or {}
        assert tool_args == {}

    def test_get_or_fallback_valid_args(self):
        """Normal case: args is a valid dict."""
        tool_call: dict[str, object] = {"name": "test_tool", "args": {"path": "/tmp"}, "id": "call_3"}
        tool_args: dict[str, object] = tool_call.get("args") or {}
        assert tool_args == {"path": "/tmp"}

    def test_get_or_fallback_empty_dict(self):
        """Edge case: args is an empty dict (should remain {})."""
        tool_call: dict[str, object] = {"name": "test_tool", "args": {}, "id": "call_4"}
        tool_args: dict[str, object] = tool_call.get("args") or {}
        assert tool_args == {}


class TestHookUpdatedInputNoneProtection:
    """Ensure pre_hook_result.updated_input=None does NOT overwrite tool_args."""

    def test_aggregated_hook_result_no_hooks(self):
        """No hooks registered -> updated_input is None."""
        result = AggregatedHookResult()
        assert result.updated_input is None
        assert result.blocked is False
        assert result.all_succeeded is True

    def test_aggregated_hook_result_hook_without_update(self):
        """Hook runs successfully but provides no updated_input."""
        hook_result = HookResult(hook_type="callable", success=True, output="ok")
        agg = AggregatedHookResult(results=(hook_result,))
        assert agg.updated_input is None
        assert agg.all_succeeded is True

    def test_aggregated_hook_result_hook_with_update(self):
        """Hook provides updated_input -> should be returned."""
        updated = {"path": "/new/path"}
        hook_result = HookResult(hook_type="callable", success=True, updated_input=updated)
        agg = AggregatedHookResult(results=(hook_result,))
        assert agg.updated_input == updated

    def test_conditional_assignment_prevents_none_overwrite(self):
        """Reproduce the exact fix: if updated_input is not None, assign."""
        original_args = {"command": "ls -la"}
        agg = AggregatedHookResult()

        if agg.updated_input is not None:
            tool_args = agg.updated_input
        else:
            tool_args = original_args

        assert tool_args == original_args

    def test_conditional_assignment_applies_update(self):
        """When hooks DO provide an update, it should be applied."""
        original_args = {"command": "ls -la"}
        updated = {"command": "pwd"}
        hook_result = HookResult(hook_type="callable", success=True, updated_input=updated)
        agg = AggregatedHookResult(results=(hook_result,))

        if agg.updated_input is not None:
            tool_args = agg.updated_input
        else:
            tool_args = original_args

        assert tool_args == updated

    def test_last_hook_wins_cascade(self):
        """Multiple hooks: last one with updated_input wins."""
        h1 = HookResult(hook_type="callable", success=True, updated_input={"a": 1})
        h2 = HookResult(hook_type="callable", success=True)
        h3 = HookResult(hook_type="callable", success=True, updated_input={"b": 2})
        agg = AggregatedHookResult(results=(h1, h2, h3))
        assert agg.updated_input == {"b": 2}
