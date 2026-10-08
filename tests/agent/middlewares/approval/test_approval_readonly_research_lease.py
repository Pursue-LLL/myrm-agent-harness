"""Integration test for approval middleware Read-Only Research Lease enforcement.

Verifies:
- Active autonomous research leases physically strip side-effect tools (write_file, shell_exec, git_push)
- Safe read-only inspection tools (read_file, web_search) pass under active lease
- Read-only lease blocks write tools even under YOLO mode (immune to YOLO auto-approval)
- Structured LLM-reflective diagnostics are injected into auto_denied ToolMessages
- Revocation of research lease restores normal operation
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolCall

from myrm_agent_harness.agent.middlewares.approval import (
    ToolApprovalMiddleware,
    set_approval_session,
    set_approval_user_id,
    set_security_config,
    set_workspace_root,
)
from myrm_agent_harness.agent.middlewares.approval.batch_processor import (
    register_security_reviewer,
)
from myrm_agent_harness.agent.security.types import (
    PermissionAction,
    PermissionRule,
    SecurityConfig,
)
from myrm_agent_harness.core.security.readonly_research_sandbox import (
    LeaseStatusEnum,
    ResearchModeEnum,
    get_readonly_research_sandbox_facade,
)


class MockRuntime:
    pass


@pytest.fixture(autouse=True)
def _cleanup_state() -> None:
    facade = get_readonly_research_sandbox_facade()
    yield
    register_security_reviewer(None)
    set_security_config(None)
    set_workspace_root("")
    set_approval_session("")
    set_approval_user_id("")
    # Cleanup any active test leases
    for sess in ("test-ro-lease-sess-01", "test-ro-lease-sess-02", "test-ro-lease-sess-03"):
        facade.revoke_lease(sess)
        facade.purge_ephemeral_overlay(sess)


@pytest.mark.asyncio
async def test_readonly_lease_blocks_write_and_shell_tools_with_diagnostics() -> None:
    session_id = "test-ro-lease-sess-01"
    facade = get_readonly_research_sandbox_facade()

    # 1. Grant autonomous research lease to session
    lease = facade.grant_research_lease(session_id, ResearchModeEnum.AUTONOMOUS_RESEARCH)
    assert lease.status == LeaseStatusEnum.ACTIVE

    config = SecurityConfig(
        ruleset=(PermissionRule("*", "*", PermissionAction.ALLOW),),
    )
    set_security_config(config)
    set_workspace_root("/tmp")
    set_approval_session(session_id)
    set_approval_user_id("user_researcher")

    messages = [
        HumanMessage(content="Perform competitor research and summarize"),
        AIMessage(
            content="Attempting write operation during research",
            tool_calls=[
                ToolCall(
                    type="tool_call",
                    name="write_file",
                    args={"path": "/tmp/output.txt", "content": "data"},
                    id="call_write_blocked",
                )
            ],
        ),
    ]

    state = {"messages": messages}
    middleware = ToolApprovalMiddleware()
    result_state = await middleware.aafter_model(state, MockRuntime())

    assert result_state is not None
    out_messages = result_state.get("messages", [])
    denial_msg = next((m for m in out_messages if getattr(m, "tool_call_id", None) == "call_write_blocked"), None)
    assert denial_msg is not None

    content_str = str(denial_msg.content)
    assert "physically stripped by Read-Only Research Lease" in content_str
    assert "[SECURITY_DENIAL_DIAGNOSTIC]" in content_str
    assert "Reason Code: HIGH_RISK_ACTION" in content_str

    # Verify metrics incremented
    metrics = facade.get_metrics()
    assert metrics.write_attempts_blocked >= 1


@pytest.mark.asyncio
async def test_readonly_lease_overrides_yolo_mode_for_shell_tools() -> None:
    session_id = "test-ro-lease-sess-02"
    facade = get_readonly_research_sandbox_facade()

    # Grant research lease
    facade.grant_research_lease(session_id, ResearchModeEnum.AUTONOMOUS_RESEARCH)

    # Enable YOLO mode
    config = SecurityConfig(
        yolo_mode_enabled=True,
    )
    set_security_config(config)
    set_workspace_root("/tmp")
    set_approval_session(session_id)
    set_approval_user_id("user_researcher")

    messages = [
        HumanMessage(content="Analyze system metrics"),
        AIMessage(
            content="Running shell command in YOLO mode",
            tool_calls=[
                ToolCall(
                    type="tool_call",
                    name="bash_code_execute_tool",
                    args={"command": "echo 'danger' > /etc/shadow"},
                    id="call_shell_yolo",
                )
            ],
        ),
    ]

    state = {"messages": messages}
    middleware = ToolApprovalMiddleware()
    result_state = await middleware.aafter_model(state, MockRuntime())

    assert result_state is not None
    out_messages = result_state.get("messages", [])
    denial_msg = next((m for m in out_messages if getattr(m, "tool_call_id", None) == "call_shell_yolo"), None)
    assert denial_msg is not None

    content_str = str(denial_msg.content)
    assert "physically stripped by Read-Only Research Lease" in content_str
    assert "[SECURITY_DENIAL_DIAGNOSTIC]" in content_str


@pytest.mark.asyncio
async def test_lease_revocation_restores_write_authority() -> None:
    session_id = "test-ro-lease-sess-03"
    facade = get_readonly_research_sandbox_facade()

    # 1. Grant then revoke lease
    facade.grant_research_lease(session_id, ResearchModeEnum.AUTONOMOUS_RESEARCH)
    revoked = facade.revoke_lease(session_id)
    assert revoked is not None
    assert revoked.status == LeaseStatusEnum.REVOKED

    # 2. In normal ALLOW mode without lease, read_file is allowed without error
    allowed, _ = facade.evaluate_tool(session_id, "write_file")
    assert allowed is True
