"""Tests for high_risk → hideAllowAlways and _should_block_allow_always guard.

Covers:
- Auto Mode Suspended sets extra_ctx["high_risk"] = True
- build_interrupt_payload emits hideAllowAlways when high_risk
- _should_block_allow_always blocks allow_always for high_risk/smart_denied
- apply_approval_decisions ignores allow_always when high_risk
"""

import pytest
from langchain_core.messages import AIMessage, ToolCall

from myrm_agent_harness.agent.middlewares.approval import (
    set_approval_user_id,
)
from myrm_agent_harness.agent.middlewares.approval._batch_decisions import (
    _should_block_allow_always,
)
from myrm_agent_harness.agent.middlewares.approval.batch_processor import (
    apply_approval_decisions,
    build_interrupt_payload,
    evaluate_tool_batch,
    register_security_reviewer,
    reset_runtime_domains,
)
from myrm_agent_harness.agent.middlewares.approval.helpers import (
    record_denial,
    reset_denial_counter,
)
from myrm_agent_harness.agent.security.types import (
    PermissionAction,
    PermissionRule,
    SecurityConfig,
)


@pytest.fixture(autouse=True)
def _isolation():
    """Reset global state for test isolation."""
    import myrm_agent_harness.agent.security.approval_flow as approval_flow
    from myrm_agent_harness.agent.middlewares.approval import get_approval_rate_limiter
    from myrm_agent_harness.agent.security.guards.taint_tracker import reset_taint_tracker

    approval_flow._allowlist = approval_flow.Allowlist()
    reset_taint_tracker()
    reset_denial_counter()
    get_approval_rate_limiter().reset(None)
    register_security_reviewer(None)
    reset_runtime_domains()


class TestAutoModeSuspendedHighRisk:
    """Auto Mode Suspended (denial threshold breached) must set high_risk."""

    @pytest.mark.asyncio
    async def test_consecutive_breach_sets_high_risk(self):
        """3 consecutive denials → next ASK tool gets high_risk in pending."""
        for _ in range(3):
            record_denial("shell_exec")

        config = SecurityConfig(
            ruleset=(PermissionRule("file_write", "*", PermissionAction.ASK),),
            auto_mode_enabled=True,
        )

        tool_calls = [
            ToolCall(
                type="tool_call",
                name="file_write_tool",
                args={"path": "/tmp/x", "content": "y"},
                id="c1",
            ),
        ]

        _approved, _denied, pending = await evaluate_tool_batch(
            tool_calls,
            config,
            is_cron=False,
            workspace_root="/tmp",
            session_key="s",
            args_hashes={},
        )

        assert len(pending) == 1
        extra_ctx = pending[0][4]
        assert extra_ctx is not None
        assert extra_ctx.get("high_risk") is True

    @pytest.mark.asyncio
    async def test_total_breach_sets_high_risk(self):
        """20 total denials → next ASK tool gets high_risk in pending."""
        for i in range(20):
            record_denial(f"tool_{i}")

        config = SecurityConfig(
            ruleset=(PermissionRule("file_write", "*", PermissionAction.ASK),),
            auto_mode_enabled=True,
        )

        tool_calls = [
            ToolCall(
                type="tool_call",
                name="file_write_tool",
                args={"path": "/tmp/x", "content": "y"},
                id="c1",
            ),
        ]

        _approved, _denied, pending = await evaluate_tool_batch(
            tool_calls,
            config,
            is_cron=False,
            workspace_root="/tmp",
            session_key="s",
            args_hashes={},
        )

        assert len(pending) == 1
        extra_ctx = pending[0][4]
        assert extra_ctx is not None
        assert extra_ctx.get("high_risk") is True

    @pytest.mark.asyncio
    async def test_no_breach_no_high_risk(self):
        """Without threshold breach, normal ASK does NOT set high_risk."""
        config = SecurityConfig(
            ruleset=(PermissionRule("file_write", "*", PermissionAction.ASK),),
            auto_mode_enabled=True,
        )

        tool_calls = [
            ToolCall(
                type="tool_call",
                name="file_write_tool",
                args={"path": "/tmp/x", "content": "y"},
                id="c1",
            ),
        ]

        _approved, _denied, pending = await evaluate_tool_batch(
            tool_calls,
            config,
            is_cron=False,
            workspace_root="/tmp",
            session_key="s",
            args_hashes={},
        )

        assert len(pending) == 1
        extra_ctx = pending[0][4]
        assert extra_ctx is None or extra_ctx.get("high_risk") is not True


class TestBuildInterruptPayloadHighRisk:
    """build_interrupt_payload must set hideAllowAlways for high_risk items."""

    def test_high_risk_hides_allow_always(self):
        """Pending item with high_risk → reviewConfig.hideAllowAlways = True."""
        pending = [
            (
                0,
                ToolCall(
                    type="tool_call",
                    name="bash_code_execute_tool",
                    args={"command": "docker run --rm alpine"},
                    id="c1",
                ),
                "code_interpreter",
                "Auto Mode Suspended: denial threshold breached",
                {"high_risk": True},
            )
        ]

        payload, indices = build_interrupt_payload(pending, "session-1")

        assert indices == [0]
        review_config = payload["reviewConfigs"][0]
        assert review_config.get("hideAllowAlways") is True
        assert "edit" in review_config["allowedDecisions"]

    def test_normal_pending_no_hide(self):
        """Pending item without high_risk → no hideAllowAlways."""
        pending = [
            (
                0,
                ToolCall(
                    type="tool_call",
                    name="file_write_tool",
                    args={"path": "/tmp/x", "content": "y"},
                    id="c1",
                ),
                "file_write",
                "ASK",
                None,
            )
        ]

        payload, _ = build_interrupt_payload(pending, "session-1")

        review_config = payload["reviewConfigs"][0]
        assert "hideAllowAlways" not in review_config

    def test_mixed_high_risk_and_normal(self):
        """Batch with one high_risk and one normal → only first has hideAllowAlways."""
        pending = [
            (
                0,
                ToolCall(
                    type="tool_call",
                    name="bash_code_execute_tool",
                    args={"command": "rm -rf /"},
                    id="c1",
                ),
                "code_interpreter",
                "Shell threat detected",
                {"high_risk": True},
            ),
            (
                1,
                ToolCall(
                    type="tool_call",
                    name="file_write_tool",
                    args={"path": "/tmp/x", "content": "safe"},
                    id="c2",
                ),
                "file_write",
                "ASK",
                None,
            ),
        ]

        payload, indices = build_interrupt_payload(pending, "session-1")

        assert len(indices) == 2
        assert payload["reviewConfigs"][0].get("hideAllowAlways") is True
        assert "hideAllowAlways" not in payload["reviewConfigs"][1]


class TestShouldBlockAllowAlways:
    """Unit tests for _should_block_allow_always guard."""

    def test_blocks_high_risk(self):
        tool_call = {"name": "bash_code_execute_tool", "args": {"command": "ls"}}
        assert _should_block_allow_always(tool_call, {"high_risk": True}) is True

    def test_blocks_smart_denied(self):
        tool_call = {"name": "bash_code_execute_tool", "args": {"command": "ls"}}
        assert _should_block_allow_always(tool_call, {"smart_denied": True}) is True

    def test_allows_normal(self):
        tool_call = {"name": "file_write_tool", "args": {"path": "/tmp/x"}}
        assert _should_block_allow_always(tool_call, None) is False

    def test_allows_empty_extra_ctx(self):
        tool_call = {"name": "file_write_tool", "args": {"path": "/tmp/x"}}
        assert _should_block_allow_always(tool_call, {}) is False

    def test_blocks_both_flags_set(self):
        tool_call = {"name": "bash_code_execute_tool", "args": {"command": "test"}}
        assert _should_block_allow_always(
            tool_call, {"high_risk": True, "smart_denied": True}
        ) is True


class TestApplyDecisionsHighRiskBlocksAllowAlways:
    """apply_approval_decisions must ignore allow_always when high_risk."""

    @pytest.mark.asyncio
    async def test_high_risk_ignores_allow_always(self):
        """User sends allowAlways for a high_risk item → NOT saved to allowlist."""
        from myrm_agent_harness.agent.security.approval_flow import get_allowlist

        set_approval_user_id("user1")

        ai_msg = AIMessage(
            content="test",
            tool_calls=[
                ToolCall(
                    type="tool_call",
                    name="bash_code_execute_tool",
                    args={"command": "docker run --rm alpine"},
                    id="c1",
                ),
            ],
        )

        decisions = [{"type": "approve", "extensions": {"allowAlways": True}}]
        pending = [
            (
                0,
                ai_msg.tool_calls[0],
                "code_interpreter",
                "Auto Mode Suspended",
                {"high_risk": True},
            ),
        ]

        revised, messages, _guidance = await apply_approval_decisions(
            decisions,
            ai_msg,
            auto_denied=[],
            pending_approval=pending,
            interrupt_indices=[0],
            args_hashes={0: "hash123"},
        )

        assert len(revised) == 1, "Tool call should still be approved (once)"
        assert len(messages) == 0

        allowlist = get_allowlist()
        assert not allowlist.check("user1", "code_interpreter"), (
            "high_risk override must NOT write to allowlist"
        )

    @pytest.mark.asyncio
    async def test_normal_allow_always_works(self):
        """Normal (non-high_risk) allowAlways should persist to allowlist."""
        from myrm_agent_harness.agent.security.approval_flow import get_allowlist

        set_approval_user_id("user1")

        ai_msg = AIMessage(
            content="test",
            tool_calls=[
                ToolCall(
                    type="tool_call",
                    name="file_write_tool",
                    args={"path": "/tmp/x", "content": "y"},
                    id="c1",
                ),
            ],
        )

        decisions = [{"type": "approve", "extensions": {"allowAlways": True}}]
        pending = [
            (0, ai_msg.tool_calls[0], "file_write", "ASK", None),
        ]

        revised, _messages, _guidance = await apply_approval_decisions(
            decisions,
            ai_msg,
            auto_denied=[],
            pending_approval=pending,
            interrupt_indices=[0],
            args_hashes={0: "hash456"},
        )

        assert len(revised) == 1
        allowlist = get_allowlist()
        assert allowlist.check("user1", "file_write"), (
            "Normal allowAlways should persist to allowlist"
        )
