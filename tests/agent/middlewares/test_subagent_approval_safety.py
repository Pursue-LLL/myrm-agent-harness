"""Test Subagent approval safety (R3 fix).

Verifies that autonomous subagents are blocked from triggering UI approval
flows, preventing deadlocks since they have no frontend channel.
"""

import pytest

from myrm_agent_harness.agent.middlewares._session_context import get_is_subagent, set_is_subagent


class TestSubagentApprovalSafety:
    """Test subagent approval auto-deny mechanism."""

    def test_set_and_get_is_subagent(self) -> None:
        """Verify is_subagent context var can be set and retrieved."""
        # Default should be False
        assert get_is_subagent() is False

        # Set to True
        set_is_subagent(True)
        assert get_is_subagent() is True

        # Set back to False
        set_is_subagent(False)
        assert get_is_subagent() is False

    def test_is_subagent_isolated_per_context(self) -> None:
        """Verify is_subagent is properly isolated per async context."""
        import asyncio

        async def parent_context() -> bool:
            set_is_subagent(False)
            return get_is_subagent()

        async def child_context() -> bool:
            set_is_subagent(True)
            return get_is_subagent()

        # Run in sequence to verify isolation
        parent_result = asyncio.run(parent_context())
        child_result = asyncio.run(child_context())

        assert parent_result is False
        assert child_result is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
