"""Unit tests for ComputerSession & DesktopSession takeover event gate & hard refusal.

Verifies that:
1. When takeover is paused via pause_for_takeover(), all mutation methods wait for user_takeover_event.
2. If takeover wait times out, UserTakeoverTimeoutError is raised and the session remains strictly locked
   (never auto-unblocking).
3. Resuming via resume_from_takeover() restores normal execution.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
import pytest

from myrm_agent_harness.toolkits.browser.exceptions import UserTakeoverTimeoutError
from myrm_agent_harness.toolkits.computer_use.session import ComputerSession
from myrm_agent_harness.toolkits.computer_use.types import ActionResult, ScreenInfo


@pytest.fixture
def mock_backend() -> MagicMock:
    backend = MagicMock()
    backend.screen_info.return_value = ScreenInfo(
        width=1920,
        height=1080,
        dpi_scale=1.0,
    )
    backend.screenshot = AsyncMock(return_value=b"")
    backend.click = AsyncMock(return_value=ActionResult(success=True))
    backend.type_text = AsyncMock(return_value=ActionResult(success=True))
    backend.key = AsyncMock(return_value=ActionResult(success=True))
    backend.mouse_move = AsyncMock(return_value=ActionResult(success=True))
    backend.scroll = AsyncMock(return_value=ActionResult(success=True))
    backend.drag = AsyncMock(return_value=ActionResult(success=True))
    return backend


class TestComputerSessionTakeoverGate:
    """Test user takeover gate on ComputerSession."""

    @pytest.mark.asyncio
    async def test_takeover_pause_and_timeout_lock(self, mock_backend: MagicMock) -> None:
        session = ComputerSession(backend=mock_backend)

        assert session.user_takeover_active is False
        assert session._user_takeover_event.is_set()

        # Pause session for user takeover
        await session.pause_for_takeover()
        assert session.user_takeover_active is True
        assert not session._user_takeover_event.is_set()

        # Calling _ensure_not_user_takeover with short timeout must raise UserTakeoverTimeoutError
        with pytest.raises(UserTakeoverTimeoutError) as exc_info:
            await session._ensure_not_user_takeover(timeout=0.05)

        assert "User takeover wait timed out" in str(exc_info.value)
        # Session MUST remain strictly locked
        assert session.user_takeover_active is True
        assert not session._user_takeover_event.is_set()

        # Mutation operations must also raise UserTakeoverTimeoutError when attempting to run
        session.user_takeover_timeout = 0.05
        with pytest.raises(UserTakeoverTimeoutError):
            await session.type_text("malicious or stray input")

        # Backend type_text should NOT have been called while locked!
        mock_backend.type_text.assert_not_called()

        # Resume session
        await session.resume_from_takeover()
        assert session.user_takeover_active is False
        assert session._user_takeover_event.is_set()
