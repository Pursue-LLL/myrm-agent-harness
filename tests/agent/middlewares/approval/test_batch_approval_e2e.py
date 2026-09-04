"""E2E test for batch approval using after_model hook.

Verifies that:
1. Multiple tools requiring approval are batched into a single interrupt()
2. interrupt() is called synchronously (not in a task)
3. Decisions are correctly mapped to tool calls
4. Auto-approved and auto-denied tools are handled correctly
"""

import pytest
from langchain_core.messages import AIMessage, ToolCall

from myrm_agent_harness.agent.middlewares.approval import (
    ToolApprovalMiddleware,
    set_approval_session,
    set_approval_user_id,
    set_security_config,
    set_workspace_root,
)
from myrm_agent_harness.agent.security.types import PermissionAction, PermissionRule, SecurityConfig


class MockRuntime:
    """Mock runtime for testing."""

    pass


@pytest.fixture(autouse=True)
def _approval_e2e_isolation() -> None:
    """Reset global singletons so order of other test modules cannot pollute batch approval."""
    import myrm_agent_harness.agent.security.approval_flow as approval_flow
    from myrm_agent_harness.agent.middlewares.approval import get_approval_rate_limiter, reset_denial_counter
    from myrm_agent_harness.agent.security.guards.taint_tracker import reset_taint_tracker

    approval_flow._allowlist = approval_flow.Allowlist()
    reset_taint_tracker()
    reset_denial_counter()
    get_approval_rate_limiter().reset(None)


@pytest.fixture
def mock_security_config():
    """Security config requiring approval for code_interpreter only."""
    return SecurityConfig(
        ruleset=(
            PermissionRule("*", "*", PermissionAction.ALLOW),
            PermissionRule("code_interpreter", "*", PermissionAction.ASK),
        )
    )


@pytest.mark.asyncio
async def test_batch_approval_single_interrupt(mock_security_config, monkeypatch):
    """Test that multiple tools requiring approval trigger a single interrupt()."""
    set_security_config(mock_security_config)
    set_workspace_root("/tmp")
    set_approval_session("test-session")
    set_approval_user_id("user123")

    interrupt_call_count = 0
    captured_payload = None

    def mock_interrupt(payload):
        nonlocal interrupt_call_count, captured_payload
        interrupt_call_count += 1
        captured_payload = payload

        return {
            "decisions": [
                {"type": "approve"},
                {"type": "reject", "feedback": "Too risky"},
                {"type": "edit", "args": {"command": "ls -l"}},
            ]
        }

    monkeypatch.setattr("myrm_agent_harness.agent.middlewares.approval.middleware.interrupt", mock_interrupt)

    middleware = ToolApprovalMiddleware()

    state = {
        "messages": [
            AIMessage(
                content="I'll help you with that.",
                tool_calls=[
                    ToolCall(
                        type="tool_call",
                        name="bash_code_execute_tool",
                        args={"command": "python3 setup.py install"},
                        id="call_1",
                    ),
                    ToolCall(
                        type="tool_call", name="bash_code_execute_tool", args={"command": "node server.js"}, id="call_2"
                    ),
                    ToolCall(
                        type="tool_call", name="bash_code_execute_tool", args={"command": "ruby deploy.rb"}, id="call_3"
                    ),
                ],
            )
        ]
    }

    result = await middleware.aafter_model(state, MockRuntime())

    assert result is not None, "Should return modified state"

    assert interrupt_call_count == 1, f"Should call interrupt() exactly once, got {interrupt_call_count}"

    assert captured_payload is not None
    action_requests = captured_payload["actionRequests"]
    assert len(action_requests) == 3, "Should batch 3 bash tools"

    assert action_requests[0]["action"] == "bash_code_execute_tool"
    assert action_requests[1]["action"] == "bash_code_execute_tool"
    assert action_requests[2]["action"] == "bash_code_execute_tool"

    messages = result["messages"]
    modified_ai_msg = messages[0]
    assert isinstance(modified_ai_msg, AIMessage)

    assert len(modified_ai_msg.tool_calls) == 2, (
        "Should have 2 approved/edited tool calls (call_1 approved, call_3 edited)"
    )
    assert modified_ai_msg.tool_calls[0]["id"] == "call_1"
    assert modified_ai_msg.tool_calls[1]["id"] == "call_3"
    assert modified_ai_msg.tool_calls[1]["args"]["command"] == "ls -l", "call_3 should be edited"

    tool_messages = [msg for msg in messages[1:] if hasattr(msg, "tool_call_id")]
    rejected = [msg for msg in tool_messages if "rejected" in msg.content.lower()]
    assert len(rejected) == 1, "Should have 1 artificial ToolMessage for rejected tool"
    assert rejected[0].tool_call_id == "call_2"


@pytest.mark.asyncio
async def test_all_auto_approved():
    """Test that when all tools are auto-approved, no interrupt() is called."""
    config = SecurityConfig(ruleset=(PermissionRule("*", "*", PermissionAction.ALLOW),))
    set_security_config(config)
    set_workspace_root("/tmp")
    set_approval_session("test-session")
    set_approval_user_id("")

    middleware = ToolApprovalMiddleware()

    state = {
        "messages": [
            AIMessage(
                content="Reading files.",
                tool_calls=[
                    ToolCall(type="tool_call", name="read_file", args={"path": "test.txt"}, id="call_1"),
                    ToolCall(type="tool_call", name="read_file", args={"path": "config.json"}, id="call_2"),
                ],
            )
        ]
    }

    result = await middleware.aafter_model(state, MockRuntime())

    assert result is None, "Should return None when no interrupt needed"


@pytest.mark.asyncio
async def test_mixed_auto_and_manual(monkeypatch):
    """Test mix of auto-approved and manual approval tools."""
    ruleset = (
        PermissionRule("*", "*", PermissionAction.ALLOW),
        PermissionRule("code_interpreter", "*", PermissionAction.ASK),
    )

    config = SecurityConfig(ruleset=ruleset)
    set_security_config(config)
    set_workspace_root("/tmp")
    set_approval_session("test-session")
    set_approval_user_id("user123")

    def mock_interrupt(payload):
        action_requests = payload["actionRequests"]
        assert len(action_requests) == 2, "Both bash tools should need approval"
        assert action_requests[0]["action"] == "bash_code_execute_tool"
        assert action_requests[1]["action"] == "bash_code_execute_tool"

        return {
            "decisions": [
                {"type": "approve"},
                {"type": "approve"},
            ]
        }

    monkeypatch.setattr("myrm_agent_harness.agent.middlewares.approval.middleware.interrupt", mock_interrupt)

    middleware = ToolApprovalMiddleware()

    state = {
        "messages": [
            AIMessage(
                content="Mixed operations.",
                tool_calls=[
                    ToolCall(type="tool_call", name="read_file", args={"path": "test.txt"}, id="call_1"),
                    ToolCall(
                        type="tool_call",
                        name="bash_code_execute_tool",
                        args={"command": "python3 setup.py install"},
                        id="call_2",
                    ),
                    ToolCall(
                        type="tool_call", name="bash_code_execute_tool", args={"command": "node server.js"}, id="call_3"
                    ),
                ],
            )
        ]
    }

    result = await middleware.aafter_model(state, MockRuntime())

    assert result is not None

    messages = result["messages"]
    modified_ai_msg = messages[0]

    assert len(modified_ai_msg.tool_calls) == 3, "All 3 tools should remain (all approved)"
    assert modified_ai_msg.tool_calls[0]["id"] == "call_1"
    assert modified_ai_msg.tool_calls[1]["id"] == "call_2"
    assert modified_ai_msg.tool_calls[2]["id"] == "call_3"


@pytest.mark.asyncio
async def test_time_bound_allow_always_batch_decision(mock_security_config, monkeypatch):
    """Test that allow_always with duration/ttl_seconds adds time-bound grant."""
    import time
    from myrm_agent_harness.agent.security.approval_flow import get_allowlist

    set_security_config(mock_security_config)
    set_workspace_root("/tmp")
    set_approval_session("test-session")
    set_approval_user_id("user_time_bound")

    allowlist = get_allowlist()
    now = time.time()
    mock_called = False

    def mock_interrupt(payload):
        nonlocal mock_called
        mock_called = True
        return {
            "decisions": [
                {
                    "type": "approve",
                    "allow_always": {
                        "tool": True,
                        "duration": "1h",
                        "ttl_seconds": 3600,
                    },
                }
            ]
        }

    monkeypatch.setattr("myrm_agent_harness.agent.middlewares.approval.middleware.interrupt", mock_interrupt)

    middleware = ToolApprovalMiddleware()
    state = {
        "messages": [
            AIMessage(
                content="Execute bash command.",
                tool_calls=[
                    ToolCall(
                        type="tool_call",
                        name="bash_code_execute_tool",
                        args={"command": "python3 setup.py install"},
                        id="call_tb",
                    )
                ],
            )
        ]
    }

    result = await middleware.aafter_model(state, MockRuntime())
    assert mock_called is True
    assert result is not None

    # Verify allowlist has time-bound grant
    assert allowlist.check("user_time_bound", "code_interpreter", "bash_code_execute_tool", None) is True
    entries = allowlist._entries.get("user_time_bound", {})
    entry = next(e for e in entries.values() if e.tool_name == "bash_code_execute_tool")
    assert entry.expires_at is not None
    assert abs(entry.expires_at - (now + 3600)) < 5.0

    # Verify allowlist has time-bound grant
    assert allowlist.check("user_time_bound", "code_interpreter", "bash_code_execute_tool", None) is True
    entries = allowlist._entries.get("user_time_bound", {})
    entry = next(e for e in entries.values() if e.tool_name == "bash_code_execute_tool")
    assert entry.expires_at is not None
    assert abs(entry.expires_at - (now + 3600)) < 5.0
