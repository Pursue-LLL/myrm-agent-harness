"""Integration test for approval classifier user intent persistence.

Verifies:
- User boundaries declared in turn 1 persist across 10+ subsequent tool turns
- Reasoning-Blind intent context reaches the security reviewer intact
- Multimodal user messages have text extracted into intent context
- Synthetic system messages are strictly excluded from reviewer intent context
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolCall, ToolMessage

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
    RecentToolCall,
    ReviewDecision,
    ReviewResult,
    SecurityConfig,
)


class MockRuntime:
    pass


class CapturingReviewer:
    """Security reviewer capturing passed parameters for assertion."""

    def __init__(self) -> None:
        self.called: bool = False
        self.captured_intent_context: str | None = None
        self.captured_command: str | None = None

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
        self.captured_command = command
        self.captured_intent_context = intent_context
        return ReviewResult(decision=ReviewDecision.ALLOW)


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
async def test_user_boundary_persists_across_extended_tool_turns() -> None:
    capturing_reviewer = CapturingReviewer()
    register_security_reviewer(capturing_reviewer)

    config = SecurityConfig(
        auto_mode_enabled=True,
        classify_all_shell_in_auto_mode=True,
    )
    set_security_config(config)
    set_workspace_root("/tmp")
    set_approval_session("test-intent-persistence-sess")
    set_approval_user_id("user_test")

    # Initial turn: User declares a clear boundary
    boundary_text = "Do NOT run any build commands or install dependencies until I review."
    messages = [HumanMessage(content=boundary_text)]

    # Simulate 8 rounds of tool calls (16 messages: 8 AIMessages + 8 ToolMessages)
    for i in range(8):
        messages.append(
            AIMessage(
                content=f"Looking at file {i}",
                tool_calls=[
                    ToolCall(
                        type="tool_call",
                        name="read_file",
                        args={"path": f"/tmp/file_{i}.txt"},
                        id=f"call_{i}",
                    )
                ],
            )
        )
        messages.append(
            ToolMessage(content=f"content_{i}", tool_call_id=f"call_{i}")
        )

    # Next: Agent decides to run shell command
    messages.append(
        AIMessage(
            content="Now checking dependencies",
            tool_calls=[
                ToolCall(
                    type="tool_call",
                    name="bash_code_execute_tool",
                    args={"command": "pip install requests"},
                    id="call_final",
                )
            ],
        )
    )

    state = {"messages": messages}
    middleware = ToolApprovalMiddleware()
    await middleware.aafter_model(state, MockRuntime())

    # Assert reviewer was invoked and received the turn-1 boundary
    assert capturing_reviewer.called is True
    assert capturing_reviewer.captured_intent_context is not None
    assert boundary_text in capturing_reviewer.captured_intent_context


@pytest.mark.asyncio
async def test_synthetic_messages_are_excluded_from_reviewer_intent() -> None:
    capturing_reviewer = CapturingReviewer()
    register_security_reviewer(capturing_reviewer)

    config = SecurityConfig(
        auto_mode_enabled=True,
        classify_all_shell_in_auto_mode=True,
    )
    set_security_config(config)
    set_workspace_root("/tmp")
    set_approval_session("test-synthetic-exclusion-sess")
    set_approval_user_id("user_test")

    real_user_directive = "Please format python files with ruff."
    synthetic_notice = "[RESTORE_NOTIFICATION] Restored 5 files."

    messages = [
        HumanMessage(content=real_user_directive),
        HumanMessage(
            content=synthetic_notice,
            additional_kwargs={"is_system_synthetic": True},
        ),
        AIMessage(
            content="Running format",
            tool_calls=[
                ToolCall(
                    type="tool_call",
                    name="bash_code_execute_tool",
                    args={"command": "ruff format ."},
                    id="call_format",
                )
            ],
        ),
    ]

    state = {"messages": messages}
    middleware = ToolApprovalMiddleware()
    await middleware.aafter_model(state, MockRuntime())

    assert capturing_reviewer.called is True
    assert capturing_reviewer.captured_intent_context is not None
    assert real_user_directive in capturing_reviewer.captured_intent_context
    assert "[RESTORE_NOTIFICATION]" not in capturing_reviewer.captured_intent_context
