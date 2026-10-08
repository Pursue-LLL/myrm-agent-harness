"""Integration test for approval middleware 4-way adaptive resolution bridge.

Verifies:
- Security auto-review and policy DENY decisions invoke the diagnostic bridge
- Denial messages contain structured LLM-reflective diagnostics ([SECURITY_DENIAL_DIAGNOSTIC])
- Denials are recorded in FourWayResolutionStateMachine / AutoReviewResolutionFacade
- High-risk operations stage a human handover deck card
- Non-interactive batch evaluations generate adaptive resolution diagnostics
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
    evaluate_tool_batch,
    register_security_reviewer,
)
from myrm_agent_harness.agent.security.types import (
    RecentToolCall,
    ReviewDecision,
    ReviewResult,
    SecurityConfig,
)
from myrm_agent_harness.core.security.auto_review_resolution import (
    DenialReasonCodeEnum,
    ResolutionBranchEnum,
    get_auto_review_resolution_facade,
)


class MockRuntime:
    pass


class DenyingReviewer:
    """Security reviewer that systematically denies commands with specified reason."""

    def __init__(self, reason: str = "High risk destructive delete operation") -> None:
        self.reason = reason
        self.called = False

    async def review(
        self,
        command: str,
        *,
        workspace_root: str | None = None,
        intent_context: str | None = None,
        taint_labels: frozenset[str] | None = None,
        recent_tool_calls: tuple[RecentToolCall, ...] = (),
        model_id: str | None = None,
        trusted_domains: tuple[str, ...] = (),
    ) -> ReviewResult:
        self.called = True
        return ReviewResult(
            decision=ReviewDecision.DENY,
            reason=self.reason,
        )


@pytest.fixture(autouse=True)
def _cleanup_state() -> None:
    register_security_reviewer(None)
    yield
    register_security_reviewer(None)
    set_security_config(None)
    set_workspace_root("")
    set_approval_session("")
    set_approval_user_id("")


@pytest.mark.asyncio
async def test_policy_denial_generates_structured_diagnostic_and_stages_handover() -> None:
    session_id = "test-approval-resolution-sess-01"

    config = SecurityConfig(
        command_denylist=("rm -rf *",),
    )
    set_security_config(config)
    set_workspace_root("/tmp")
    set_approval_session(session_id)
    set_approval_user_id("user_test")

    messages = [
        HumanMessage(content="Please clean up database tables"),
        AIMessage(
            content="Deleting tables",
            tool_calls=[
                ToolCall(
                    type="tool_call",
                    name="bash_code_execute_tool",
                    args={"command": "rm -rf /data/db_backups"},
                    id="call_drop",
                )
            ],
        ),
    ]

    state = {"messages": messages}
    middleware = ToolApprovalMiddleware()
    result_state = await middleware.aafter_model(state, MockRuntime())

    assert result_state is not None

    # 1. Check generated denial message in output state
    out_messages = result_state.get("messages", [])
    denial_tool_msg = next((m for m in out_messages if getattr(m, "tool_call_id", None) == "call_drop"), None)
    assert denial_tool_msg is not None

    content_str = str(denial_tool_msg.content)
    assert "Tool execution denied by security policy:" in content_str
    assert "[SECURITY_DENIAL_DIAGNOSTIC]" in content_str
    assert "Reason Code: HIGH_RISK_ACTION" in content_str
    assert "Suggested Branch: HANDOVER_TO_USER" in content_str
    assert "1. ASK_USER" in content_str
    assert "2. TRY_ALTERNATIVE" in content_str
    assert "3. HANDOVER_TO_USER" in content_str
    assert "4. STOP_OPERATION" in content_str

    # 2. Verify state machine registration in facade
    facade = get_auto_review_resolution_facade()
    active_denial = facade.get_active_denial(session_id)
    assert active_denial is not None
    assert active_denial.reason_code == DenialReasonCodeEnum.HIGH_RISK_ACTION
    assert active_denial.suggested_branch == ResolutionBranchEnum.HANDOVER_TO_USER

    # 3. Verify handover deck card staged
    staged_cards = facade.list_staged_handovers(session_id)
    assert len(staged_cards) >= 1
    latest_card = staged_cards[-1]
    assert latest_card.prepared_command == "bash_code_execute_tool"
    assert "rm -rf" in latest_card.task_description


@pytest.mark.asyncio
async def test_non_interactive_llm_review_denial_creates_adaptive_diagnostic() -> None:
    session_id = "test-approval-resolution-sess-02"
    reviewer = DenyingReviewer("Database credential exfiltration attempt detected")
    register_security_reviewer(reviewer)

    config = SecurityConfig(
        auto_mode_enabled=True,
        classify_all_shell_in_auto_mode=True,
    )

    tool_call: ToolCall = {
        "name": "bash_code_execute_tool",
        "args": {"command": "cat /etc/credentials/db_secret.key"},
        "id": "call_leak",
        "type": "tool_call",
    }

    auto_approved, auto_denied, pending = await evaluate_tool_batch(
        tool_calls=[tool_call],
        config=config,
        is_cron=False,
        workspace_root="/tmp",
        session_key=session_id,
        args_hashes={},
        is_interactive=False,
    )

    assert len(auto_approved) == 0
    assert len(pending) == 0
    assert len(auto_denied) == 1

    idx, tc, denial_message = auto_denied[0]
    assert idx == 0
    assert tc["id"] == "call_leak"
    assert "[SECURITY_DENIAL_DIAGNOSTIC]" in denial_message
    assert "Reason Code: SENSITIVE_DATA_LEAK" in denial_message
    assert "Suggested Branch: TRY_ALTERNATIVE" in denial_message

    # Verify state machine registration
    facade = get_auto_review_resolution_facade()
    active_denial = facade.get_active_denial(session_id)
    assert active_denial is not None
    assert active_denial.reason_code == DenialReasonCodeEnum.SENSITIVE_DATA_LEAK
    assert active_denial.suggested_branch == ResolutionBranchEnum.TRY_ALTERNATIVE
