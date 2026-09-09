"""Unit tests for BrowserSession takeover timeout hard-lock mechanism.

Ensures that BrowserSession._ensure_not_user_takeover strictly raises UserTakeoverTimeoutError
and preserves lock state when a timeout occurs, preventing silent unblocking and bot ghost runs.
"""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from myrm_agent_harness.toolkits.browser.exceptions import UserTakeoverTimeoutError
from myrm_agent_harness.toolkits.browser.session.browser_session import BrowserSession


class TestBrowserTakeoverTimeoutLock:
    """Verify that timeout during user takeover raises UserTakeoverTimeoutError and keeps session locked."""

    @pytest.mark.asyncio
    async def test_ensure_not_user_takeover_timeout_raises_hard_refusal(self) -> None:
        """When user takeover wait times out, UserTakeoverTimeoutError must be raised and session remains locked."""
        mock_pool = MagicMock()
        session = BrowserSession(browser_pool=mock_pool, context_type="isolated")
        await session.pause_for_takeover()
        assert session.user_takeover_active is True
        assert not session._user_takeover_event.is_set()

        # Waiting with a tiny timeout must raise UserTakeoverTimeoutError
        with pytest.raises(UserTakeoverTimeoutError) as exc_info:
            await session._ensure_not_user_takeover(timeout=0.05)

        assert "User takeover wait timed out" in str(exc_info.value)
        # Session MUST remain locked to prevent ghost execution
        assert session.user_takeover_active is True
        assert not session._user_takeover_event.is_set()

        # Resuming must correctly unblock
        await session.resume_from_takeover()
        assert session.user_takeover_active is False
        assert session._user_takeover_event.is_set()
        # Now _ensure_not_user_takeover passes immediately without error
        await session._ensure_not_user_takeover(timeout=0.05)
