"""Tests for DesktopSession DESKTOP_VIEW_UPDATE emission."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.core.events.types import AgentEventType
from myrm_agent_harness.toolkits.computer_use.desktop_session import DesktopSession
from myrm_agent_harness.toolkits.computer_use.types import ComputerUseConfig, ScreenContext, ScreenInfo
from myrm_agent_harness.toolkits.element_ref.errors import AXPermissionRequiredError
from myrm_agent_harness.utils.runtime import progress_sink


class _CaptureSink:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def emit(self, event: dict[str, object]) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_permission_error_emits_desktop_view_update() -> None:
    backend = MagicMock()
    backend.screen_info.return_value = ScreenInfo(width=1920, height=1080, dpi_scale=1.0)
    backend.screen_context.return_value = ScreenContext(active_window="Test", mouse_x=0, mouse_y=0)

    session = DesktopSession(backend=backend, config=ComputerUseConfig())
    sink = _CaptureSink()
    progress_sink.set_tool_progress_sink(sink)

    try:
        with patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.capture_snapshot",
            side_effect=AXPermissionRequiredError("macOS"),
        ):
            result = await session.desktop_snapshot()

        assert isinstance(result, str)
        assert "Accessibility permission required" in result
        assert len(sink.events) == 1
        assert sink.events[0]["type"] == AgentEventType.DESKTOP_VIEW_UPDATE.value
        data = sink.events[0]["data"]
        assert isinstance(data, dict)
        assert data["needs_permission"] is True
    finally:
        progress_sink.set_tool_progress_sink(None)
