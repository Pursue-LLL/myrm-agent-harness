"""Integration test for approval middleware Read-Only Research Lease enforcement.

Verifies:
- Active autonomous research leases physically strip side-effect tools (file_write_tool, bash_code_execute_tool)
- Safe read-only inspection tools (file_read_tool, web_search_tool) pass under active lease
- Tools outside the allow-list that are not destructive are denied with the whitelist wording
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
    for sess in (
        "test-ro-lease-sess-01",
        "test-ro-lease-sess-02",
        "test-ro-lease-sess-03",
        "test-ro-lease-sess-04",
        "test-ro-lease-sess-05",
    ):
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
                    name="file_write_tool",
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

    # 2. Once revoked, the lease no longer strips the write tool
    allowed, _ = facade.evaluate_tool(session_id, "file_write_tool")
    assert allowed is True


def _single_call_state(call_id: str, tool_name: str, args: dict[str, object]) -> dict[str, object]:
    return {
        "messages": [
            HumanMessage(content="Research the topic"),
            AIMessage(
                content="Calling a tool during research",
                tool_calls=[ToolCall(type="tool_call", name=tool_name, args=args, id=call_id)],
            ),
        ]
    }


def _denial_for(result_state: dict[str, object] | None, call_id: str) -> object | None:
    messages = (result_state or {}).get("messages", [])
    return next((m for m in messages if getattr(m, "tool_call_id", None) == call_id), None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "args"),
    [
        ("web_search_tool", {"query": "agent security"}),
        ("file_read_tool", {"path": "/tmp/notes.txt"}),
    ],
)
async def test_readonly_lease_lets_read_tools_through(tool_name: str, args: dict[str, object]) -> None:
    session_id = "test-ro-lease-sess-04"
    get_readonly_research_sandbox_facade().grant_research_lease(session_id, ResearchModeEnum.AUTONOMOUS_RESEARCH)
    set_security_config(SecurityConfig(ruleset=(PermissionRule("*", "*", PermissionAction.ALLOW),)))
    set_workspace_root("/tmp")
    set_approval_session(session_id)
    set_approval_user_id("user_researcher")

    result_state = await ToolApprovalMiddleware().aafter_model(
        _single_call_state("call_read_ok", tool_name, args), MockRuntime()
    )

    assert _denial_for(result_state, "call_read_ok") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "args"),
    [
        ("todo_write", {"todos": []}),
        # Sub-agents run under their own approval session key, which a lease keyed by the parent session
        # cannot follow, so a leased run must not be able to start one.
        ("delegate_task_tool", {"subagent": "worker", "task": "research"}),
    ],
)
async def test_readonly_lease_denies_non_destructive_tool_outside_allow_list(
    tool_name: str, args: dict[str, object]
) -> None:
    session_id = "test-ro-lease-sess-05"
    get_readonly_research_sandbox_facade().grant_research_lease(session_id, ResearchModeEnum.AUTONOMOUS_RESEARCH)
    set_security_config(SecurityConfig(ruleset=(PermissionRule("*", "*", PermissionAction.ALLOW),)))
    set_workspace_root("/tmp")
    set_approval_session(session_id)
    set_approval_user_id("user_researcher")

    result_state = await ToolApprovalMiddleware().aafter_model(
        _single_call_state("call_blocked", tool_name, args), MockRuntime()
    )

    denial_msg = _denial_for(result_state, "call_blocked")
    assert denial_msg is not None
    content_str = str(denial_msg.content)
    assert "not in the safe read-only whitelist" in content_str
    assert "physically stripped" not in content_str
    assert "Reason Code: POLICY_VIOLATION" in content_str
