"""Unit tests for Untrusted Ingress Fence and TaintTracker ingress taint integration."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.security.guards.taint_tracker import (
    TaintLabel,
    get_taint_tracker,
    reset_taint_tracker,
)
from myrm_agent_harness.agent.security.guards.untrusted_ingress_fence import (
    DISALLOWED_UNTRUSTED_TOOLS,
    filter_untrusted_ingress_tools,
    is_tool_allowed_under_untrusted_ingress,
    is_untrusted_ingress_active,
    reset_untrusted_ingress,
    set_untrusted_ingress,
)


@pytest.fixture(autouse=True)
def clean_context():
    reset_untrusted_ingress()
    reset_taint_tracker()
    yield
    reset_untrusted_ingress()
    reset_taint_tracker()


def test_untrusted_ingress_context_switch():
    assert not is_untrusted_ingress_active()
    set_untrusted_ingress(True)
    assert is_untrusted_ingress_active()
    reset_untrusted_ingress()
    assert not is_untrusted_ingress_active()


def test_is_tool_allowed_under_untrusted_ingress():
    # Destructive tools must be blocked
    for tool in DISALLOWED_UNTRUSTED_TOOLS:
        assert not is_tool_allowed_under_untrusted_ingress(tool)
        assert not is_tool_allowed_under_untrusted_ingress(tool.upper())

    # Read-only exploration tools must be allowed
    safe_tools = ["file_read_tool", "grep_tool", "glob_tool", "web_search_tool", "memory_search_tool"]
    for tool in safe_tools:
        assert is_tool_allowed_under_untrusted_ingress(tool)


def test_filter_untrusted_ingress_tools_inactive():
    tools = ["bash_code_execute_tool", "file_read_tool", "file_write_tool"]
    # When inactive, all tools pass through
    assert filter_untrusted_ingress_tools(tools) == tools


def test_filter_untrusted_ingress_tools_active():
    set_untrusted_ingress(True)
    tools = ["bash_code_execute_tool", "file_read_tool", "file_write_tool", "grep_tool"]
    filtered = filter_untrusted_ingress_tools(tools)
    assert filtered == ["file_read_tool", "grep_tool"]


def test_taint_tracker_ingress_taint_and_sink_check():
    tracker = get_taint_tracker()
    assert not tracker.is_tainted

    tracker.record_ingress_taint(TaintLabel.UNTRUSTED_INGRESS, source="a2a_remote_peer_123")
    assert tracker.is_tainted
    assert TaintLabel.UNTRUSTED_INGRESS in tracker.labels

    # Sinks that must be blocked when UNTRUSTED_INGRESS taint is active
    assert tracker.check_sink("bash_code_execute_tool") is not None
    assert tracker.check_sink("shell_exec") is not None
    assert tracker.check_sink("file_write_tool") is not None
    assert tracker.check_sink("file_edit_tool") is not None

    # Read-only tools are clean
    assert tracker.check_sink("file_read_tool") is None
    assert tracker.check_sink("web_search_tool") is None


@pytest.mark.asyncio
async def test_batch_processor_denies_destructive_tools_under_untrusted_ingress():
    from myrm_agent_harness.agent.middlewares.approval.batch_processor import evaluate_tool_batch
    from myrm_agent_harness.agent.security.types import SecurityConfig

    config = SecurityConfig()
    set_untrusted_ingress(True)

    tool_calls = [
        {"name": "bash_code_execute_tool", "args": {"command": "ls -la"}},
        {"name": "file_write_tool", "args": {"path": "/tmp/test.txt", "content": "hi"}},
    ]
    approved, denied, pending = await evaluate_tool_batch(
        tool_calls, config, False, "/tmp", "sess_untrusted", {}
    )

    assert len(approved) == 0
    assert len(pending) == 0
    assert len(denied) == 2
    assert "Untrusted ingress fence" in denied[0][2]
    assert "Untrusted ingress fence" in denied[1][2]


@pytest.mark.asyncio
async def test_batch_processor_denies_destructive_tools_under_yolo_untrusted_ingress():
    from myrm_agent_harness.agent.middlewares.approval.batch_processor import evaluate_tool_batch
    from myrm_agent_harness.agent.security.types import SecurityConfig

    config = SecurityConfig(yolo_mode_enabled=True)
    set_untrusted_ingress(True)

    tool_calls = [
        {"name": "bash_code_execute_tool", "args": {"command": "echo pwned"}},
        {"name": "grep_tool", "args": {"query": "safe"}},
    ]
    approved, denied, _pending = await evaluate_tool_batch(
        tool_calls, config, False, "/tmp", "sess_yolo_untrusted", {}
    )

    # bash must be denied, grep should be approved under YOLO
    assert len(denied) == 1
    assert denied[0][1]["name"] == "bash_code_execute_tool"
    assert "Untrusted ingress fence" in denied[0][2]
    assert len(approved) == 1
    assert approved[0][1]["name"] == "grep_tool"


def test_cross_modal_and_subagent_tools_blocked_under_untrusted_ingress():
    """Verify that desktop control, mobile ADB, subagent delegation, cron, and skill tools are blocked."""
    high_risk_tools = [
        "desktop_interact_tool",
        "desktop_vision_tool",
        "desktop_snapshot_tool",
        "mobile_interact_tool",
        "mobile_global_tool",
        "mobile_snapshot_tool",
        "delegate_task_tool",
        "subagent_control_tool",
        "invoke_acp_agent_tool",
        "cron_manage_tool",
        "skill_manage_tool",
    ]
    for tool in high_risk_tools:
        assert not is_tool_allowed_under_untrusted_ingress(tool), f"Tool {tool} should be blocked"


def test_skill_manage_and_screen_capture_blocked_under_untrusted_ingress():
    """Verify that skill management and screen capture tools are strictly blocked."""
    tools = [
        "skill_manage_tool",
        "desktop_snapshot_tool",
        "mobile_snapshot_tool",
    ]
    for tool in tools:
        assert not is_tool_allowed_under_untrusted_ingress(tool), f"Tool {tool} should be blocked"


def test_filter_untrusted_ingress_tools_strips_cross_modal_and_delegation():
    """Verify filter_untrusted_ingress_tools removes desktop and subagent delegation tools."""
    set_untrusted_ingress(True)
    tools = [
        "desktop_interact_tool",
        "file_read_tool",
        "delegate_task_tool",
        "web_search_tool",
    ]
    filtered = filter_untrusted_ingress_tools(tools)
    assert filtered == ["file_read_tool", "web_search_tool"]


@pytest.mark.asyncio
async def test_batch_processor_denies_desktop_and_subagent_under_untrusted_ingress():
    """Verify evaluate_tool_batch rejects desktop_interact_tool and delegate_task_tool under ingress fence."""
    from myrm_agent_harness.agent.middlewares.approval.batch_processor import evaluate_tool_batch
    from myrm_agent_harness.agent.security.types import SecurityConfig

    config = SecurityConfig(yolo_mode_enabled=True)
    set_untrusted_ingress(True)

    tool_calls = [
        {"name": "desktop_interact_tool", "args": {"action": "click", "x": 100, "y": 200}},
        {"name": "delegate_task_tool", "args": {"subagent": "worker", "task": "run"}},
        {"name": "file_read_tool", "args": {"path": "/workspace/doc.md"}},
    ]
    approved, denied, _pending = await evaluate_tool_batch(
        tool_calls, config, False, "/tmp", "sess_cross_modal_test", {}
    )

    assert len(denied) == 2
    denied_names = {call[1]["name"] for call in denied}
    assert denied_names == {"desktop_interact_tool", "delegate_task_tool"}
    assert "Untrusted ingress fence" in denied[0][2]
    assert "Untrusted ingress fence" in denied[1][2]
    assert len(approved) == 1
    assert approved[0][1]["name"] == "file_read_tool"


