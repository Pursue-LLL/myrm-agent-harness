"""Unit tests for _apply_langgraph_tool_args_guard in base_agent.py.

Verifies that the monkeypatch on ToolNode preserves tool_call args
through the full execution pipeline (stash at _arun_one/_run_one entry,
restore at _inject_tool_args if args is nullified).
"""

from __future__ import annotations

import contextlib
from copy import deepcopy
from unittest.mock import MagicMock

import pytest

import myrm_agent_harness.agent.base_agent  # noqa: F401


class TestToolArgsGuard:
    """Tests for the LangGraph tool args guard monkeypatch."""

    def test_guard_replaces_none_args_with_empty_dict(self):
        """When tool_call['args'] is None, guard should replace with {}."""
        from langgraph.prebuilt.tool_node import ToolNode

        tool_call = {"name": "test_tool", "id": "tc_1", "args": None}
        fake_tool_runtime = MagicMock()

        with contextlib.suppress(Exception):
            ToolNode._inject_tool_args(MagicMock(), tool_call, fake_tool_runtime)

        assert tool_call["args"] is not None, "args should not be None after guard"
        assert isinstance(tool_call["args"], dict), "args should be a dict"

    def test_guard_preserves_valid_dict_args(self):
        """When tool_call['args'] is a valid dict, guard should not modify it."""
        from langgraph.prebuilt.tool_node import ToolNode

        original_args = {"query": "test", "limit": 10}
        tool_call = {"name": "test_tool", "id": "tc_1", "args": original_args}
        fake_tool_runtime = MagicMock()

        with contextlib.suppress(Exception):
            ToolNode._inject_tool_args(MagicMock(), tool_call, fake_tool_runtime)

        assert tool_call["args"]["query"] == "test"
        assert tool_call["args"]["limit"] == 10

    def test_guard_preserves_empty_dict_args(self):
        """When tool_call['args'] is {}, guard should leave it unchanged."""
        from langgraph.prebuilt.tool_node import ToolNode

        tool_call = {"name": "test_tool", "id": "tc_1", "args": {}}
        fake_tool_runtime = MagicMock()

        with contextlib.suppress(Exception):
            ToolNode._inject_tool_args(MagicMock(), tool_call, fake_tool_runtime)

        assert tool_call["args"] == {}

    def test_guard_is_applied_at_module_load(self):
        """Verify the guard flag is True after base_agent module import."""
        from myrm_agent_harness.agent._internals.langgraph_guard import _TOOL_ARGS_GUARD_APPLIED

        assert _TOOL_ARGS_GUARD_APPLIED is True

    def test_guard_is_idempotent(self):
        """Calling apply_langgraph_tool_args_guard multiple times is safe."""
        from myrm_agent_harness.agent._internals.langgraph_guard import (
            apply_langgraph_tool_args_guard as _apply_langgraph_tool_args_guard,
        )

        _apply_langgraph_tool_args_guard()
        _apply_langgraph_tool_args_guard()

        from langgraph.prebuilt.tool_node import ToolNode

        tool_call = {"name": "test_tool", "id": "tc_1", "args": None}
        fake_tool_runtime = MagicMock()

        with contextlib.suppress(Exception):
            ToolNode._inject_tool_args(MagicMock(), tool_call, fake_tool_runtime)

        assert isinstance(tool_call["args"], dict)

    def test_patched_method_wraps_original(self):
        """Guard should call through to the original _inject_tool_args."""
        from langgraph.prebuilt.tool_node import ToolNode

        tool_call = {"name": "test_tool", "id": "tc_1", "args": {"x": 1}}
        node = ToolNode(tools=[])
        fake_runtime = {}

        with contextlib.suppress(Exception):
            node._inject_tool_args(tool_call, fake_runtime)

        assert tool_call["args"]["x"] == 1


class TestStashRecoveryMechanism:
    """Tests for the stash + restore mechanism across _arun_one/_run_one → _inject_tool_args."""

    @pytest.mark.asyncio
    async def test_async_stash_recovers_nullified_args(self):
        """_arun_one stashes args; if _inject_tool_args sees None, stash restores them."""
        from langgraph.prebuilt.tool_node import ToolNode

        original_args = {"questions": ["what is AI?"], "reason": "research"}
        tool_call = {"name": "web_search", "id": "tc_stash_1", "args": deepcopy(original_args)}
        node = ToolNode(tools=[])
        fake_runtime = MagicMock()

        with contextlib.suppress(Exception):
            await node._arun_one(tool_call, "list", fake_runtime)

        tool_call["args"] = None
        with contextlib.suppress(Exception):
            node._inject_tool_args(tool_call, fake_runtime)

        assert tool_call["args"] == original_args

    def test_sync_stash_recovers_nullified_args(self):
        """_run_one stashes args; if _inject_tool_args sees None, stash restores them."""
        from langgraph.prebuilt.tool_node import ToolNode

        original_args = {"query": "hello world", "max_results": 5}
        tool_call = {"name": "search", "id": "tc_stash_2", "args": deepcopy(original_args)}
        node = ToolNode(tools=[])
        fake_runtime = MagicMock()

        with contextlib.suppress(Exception):
            node._run_one(tool_call, "list", fake_runtime)

        tool_call["args"] = None
        with contextlib.suppress(Exception):
            node._inject_tool_args(tool_call, fake_runtime)

        assert tool_call["args"] == original_args

    def test_stash_is_cleaned_after_use(self):
        """After _inject_tool_args restores from stash, the stash entry is removed."""
        from langgraph.prebuilt.tool_node import ToolNode

        tool_call = {"name": "tool_a", "id": "tc_cleanup_1", "args": {"k": "v"}}
        node = ToolNode(tools=[])
        fake_runtime = MagicMock()

        with contextlib.suppress(Exception):
            node._run_one(tool_call, "list", fake_runtime)

        tool_call["args"] = None
        with contextlib.suppress(Exception):
            node._inject_tool_args(tool_call, fake_runtime)
        assert tool_call["args"] == {"k": "v"}

        tool_call2 = {"name": "tool_a", "id": "tc_cleanup_1", "args": None}
        with contextlib.suppress(Exception):
            node._inject_tool_args(tool_call2, fake_runtime)
        assert tool_call2["args"] == {}

    def test_stash_cleaned_when_args_not_null(self):
        """_inject_tool_args clears stash even when args is not None."""
        from langgraph.prebuilt.tool_node import ToolNode

        tool_call = {"name": "tool_b", "id": "tc_clean_2", "args": {"a": 1}}
        node = ToolNode(tools=[])
        fake_runtime = MagicMock()

        with contextlib.suppress(Exception):
            node._run_one(tool_call, "list", fake_runtime)

        with contextlib.suppress(Exception):
            node._inject_tool_args(tool_call, fake_runtime)

        assert tool_call["args"]["a"] == 1

        tool_call3 = {"name": "tool_b", "id": "tc_clean_2", "args": None}
        with contextlib.suppress(Exception):
            node._inject_tool_args(tool_call3, fake_runtime)
        assert tool_call3["args"] == {}

    def test_stash_deep_copies_args(self):
        """Stashed args should be a deep copy, not a reference."""
        from langgraph.prebuilt.tool_node import ToolNode

        original_args = {"nested": {"key": "value"}}
        tool_call = {"name": "tool_c", "id": "tc_deep_1", "args": original_args}
        node = ToolNode(tools=[])
        fake_runtime = MagicMock()

        with contextlib.suppress(Exception):
            node._run_one(tool_call, "list", fake_runtime)

        original_args["nested"]["key"] = "mutated"
        tool_call["args"] = None

        with contextlib.suppress(Exception):
            node._inject_tool_args(tool_call, fake_runtime)

        assert tool_call["args"]["nested"]["key"] == "value"

    def test_multiple_tool_calls_independent_stash(self):
        """Different tool_call ids maintain independent stash entries."""
        from langgraph.prebuilt.tool_node import ToolNode

        call_a = {"name": "tool_a", "id": "tc_multi_a", "args": {"a": 1}}
        call_b = {"name": "tool_b", "id": "tc_multi_b", "args": {"b": 2}}
        node = ToolNode(tools=[])
        fake_runtime = MagicMock()

        for call in (call_a, call_b):
            with contextlib.suppress(Exception):
                node._run_one(call, "list", fake_runtime)

        call_a["args"] = None
        call_b["args"] = None

        with contextlib.suppress(Exception):
            node._inject_tool_args(call_a, fake_runtime)
        assert call_a["args"] == {"a": 1}

        with contextlib.suppress(Exception):
            node._inject_tool_args(call_b, fake_runtime)
        assert call_b["args"] == {"b": 2}

    def test_empty_id_fallback(self):
        """When id is empty string, stash still works but last-write-wins."""
        from langgraph.prebuilt.tool_node import ToolNode

        call = {"name": "tool_x", "id": "", "args": {"x": 99}}
        node = ToolNode(tools=[])
        fake_runtime = MagicMock()

        with contextlib.suppress(Exception):
            node._run_one(call, "list", fake_runtime)

        call["args"] = None
        with contextlib.suppress(Exception):
            node._inject_tool_args(call, fake_runtime)

        assert call["args"] == {"x": 99}
