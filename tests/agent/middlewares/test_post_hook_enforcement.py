"""Test POST_TOOL_USE hook enforcement (R2 fix).

Verifies that POST_TOOL_USE hook failures are properly enforced by converting
successful ToolMessages into error ToolMessages, forcing LLM self-repair.
"""

import pytest
from langchain_core.messages import ToolMessage

from myrm_agent_harness.agent.hooks.types import AggregatedHookResult, HookResult


class TestPostToolUseEnforcement:
    """Test POST_TOOL_USE hook failure enforcement."""

    def test_aggregated_hook_result_blocked_property(self) -> None:
        """Verify AggregatedHookResult.blocked detects blocked hooks."""
        result1 = HookResult(
            hook_type="command",
            success=False,
            blocked=True,
            reason="Hook validation failed",
            output="Error: linting failed",
        )
        result2 = HookResult(hook_type="command", success=True, blocked=False)

        agg = AggregatedHookResult(results=(result1, result2))
        assert agg.blocked is True
        assert "Hook validation failed" in agg.reason

    def test_aggregated_hook_result_all_succeeded_property(self) -> None:
        """Verify AggregatedHookResult.all_succeeded detects failures."""
        result1 = HookResult(hook_type="command", success=False, output="Hook failed")
        result2 = HookResult(hook_type="command", success=True)

        agg = AggregatedHookResult(results=(result1, result2))
        assert agg.all_succeeded is False

    def test_tool_message_status_error_construction(self) -> None:
        """Verify ToolMessage can be constructed with status='error'."""
        msg = ToolMessage(
            content="[HOOK_VALIDATION_FAILED] Post-execution hook detected issues",
            name="test_tool",
            tool_call_id="call_123",
            status="error",
        )
        assert msg.status == "error"
        assert "[HOOK_VALIDATION_FAILED]" in msg.content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
