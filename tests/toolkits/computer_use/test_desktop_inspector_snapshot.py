"""Tests for DesktopSession inspector snapshot screen metadata."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.core.events.types import AgentEventType
from myrm_agent_harness.toolkits.computer_use.desktop_session import DesktopSession
from myrm_agent_harness.toolkits.computer_use.types import ComputerUseConfig, ScreenInfo
from myrm_agent_harness.toolkits.element_ref.errors import AXPermissionRequiredError
from myrm_agent_harness.toolkits.element_ref.types import BBox, ElementRef, SnapshotMeta
from myrm_agent_harness.utils.runtime import progress_sink


class _CaptureSink:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def emit(self, event: dict[str, object]) -> None:
        self.events.append(event)


def test_snapshot_screen_fields_reads_backend_screen_info() -> None:
    backend = MagicMock()
    backend.screen_info.return_value = ScreenInfo(width=1440, height=900, dpi_scale=2.0)
    session = DesktopSession(backend=backend, config=ComputerUseConfig())

    assert session._snapshot_screen_fields() == {
        "screen_width": 1440,
        "screen_height": 900,
        "dpi_scale": 2.0,
    }


@pytest.mark.asyncio
async def test_export_inspector_snapshot_permission_includes_screen_fields() -> None:
    backend = MagicMock()
    backend.screen_info.return_value = ScreenInfo(width=1680, height=1050, dpi_scale=2.0)
    session = DesktopSession(backend=backend, config=ComputerUseConfig())

    with patch(
        "myrm_agent_harness.toolkits.computer_use.desktop_session.capture_snapshot",
        side_effect=AXPermissionRequiredError("macOS"),
    ):
        payload = await session.export_inspector_snapshot()

    assert payload["needs_permission"] is True
    assert payload["screen_width"] == 1680
    assert payload["screen_height"] == 1050
    assert payload["dpi_scale"] == 2.0


@pytest.mark.asyncio
async def test_emit_view_update_includes_screen_fields() -> None:
    backend = MagicMock()
    backend.screen_info.return_value = ScreenInfo(width=1920, height=1080, dpi_scale=1.0)
    session = DesktopSession(backend=backend, config=ComputerUseConfig())
    sink = _CaptureSink()
    progress_sink.set_tool_progress_sink(sink)

    meta = SnapshotMeta(
        ref_count=1,
        app_name="App",
        window_title="Window",
        scope="foreground",
        needs_permission=False,
    )
    refs = {
        "d1": ElementRef(
            ref_id="d1",
            role="button",
            name="OK",
            bbox=BBox(0, 0, 10, 10),
            backend_key="k",
        )
    }

    try:
        await session._emit_view_update(
            screenshot_base64="img",
            screenshot_size=(1280, 800),
            refs=refs,
            meta=meta,
        )

        assert len(sink.events) == 1
        data = sink.events[0]["data"]
        assert isinstance(data, dict)
        assert data["screen_width"] == 1920
        assert data["screen_height"] == 1080
        assert data["dpi_scale"] == 1.0
        assert data["viewport_width"] == 1280
        assert data["viewport_height"] == 800
        assert sink.events[0]["type"] == AgentEventType.DESKTOP_VIEW_UPDATE.value
    finally:
        progress_sink.set_tool_progress_sink(None)


@pytest.mark.asyncio
async def test_emit_view_update_invokes_view_update_callback() -> None:
    backend = MagicMock()
    backend.screen_info.return_value = ScreenInfo(width=1440, height=900, dpi_scale=1.0)
    callback = MagicMock()
    session = DesktopSession(backend=backend, config=ComputerUseConfig(), view_update_callback=callback)

    meta = SnapshotMeta(
        ref_count=0,
        app_name="App",
        window_title="Window",
        scope="foreground",
        needs_permission=False,
    )

    await session._emit_view_update(
        screenshot_base64="",
        screenshot_size=(0, 0),
        refs={},
        meta=meta,
    )

    callback.assert_called_once()
    payload = callback.call_args.args[0]
    assert payload["screen_width"] == 1440
    assert payload["screen_height"] == 900
