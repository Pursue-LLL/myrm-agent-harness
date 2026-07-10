"""Integration tests for DesktopSession SOM wiring."""

from __future__ import annotations

import base64
import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from myrm_agent_harness.toolkits.computer_use.coordinate_scaler import CoordinateScaler
from myrm_agent_harness.toolkits.computer_use.desktop_session import DesktopSession
from myrm_agent_harness.toolkits.computer_use.dref.types import BBox, ElementRef, SnapshotMeta
from myrm_agent_harness.toolkits.computer_use.types import ActionResult, ComputerUseConfig, ScreenInfo


def _jpeg_base64(width: int = 400, height: int = 300) -> str:
    image = Image.new("RGB", (width, height), color=(200, 200, 200))
    buf = io.BytesIO()
    image.save(buf, format="JPEG")
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


@pytest.fixture
def session() -> DesktopSession:
    backend = MagicMock()
    backend.screen_info.return_value = ScreenInfo(width=800, height=600, dpi_scale=1.0)
    return DesktopSession(backend=backend, config=ComputerUseConfig())


@pytest.mark.asyncio
async def test_desktop_snapshot_include_screenshot_applies_som_and_nth(session: DesktopSession) -> None:
    meta = SnapshotMeta(
        ref_count=1,
        app_name="Settings",
        window_title="General",
        scope="foreground",
    )
    refs = {
        "d1": ElementRef(
            ref_id="d1",
            role="AXButton",
            name="OK",
            bbox=BBox(100, 100, 80, 40),
            backend_key="k1",
        )
    }
    original_b64 = _jpeg_base64()
    shot = ActionResult(
        success=True,
        screenshot_base64=original_b64,
        screenshot_size=(400, 300),
    )
    session.take_screenshot = AsyncMock(return_value=shot)  # type: ignore[method-assign]
    session._scaler = CoordinateScaler(
        screen_width=800,
        screen_height=600,
        sent_width=400,
        sent_height=300,
        dpi_scale=1.0,
    )

    with patch(
        "myrm_agent_harness.toolkits.computer_use.desktop_session.capture_snapshot",
        return_value=(meta, refs),
    ):
        result = await session.desktop_snapshot(include_screenshot=True)

    assert isinstance(result, list)
    assert len(result) == 2
    first = result[0]
    text_content = first.get("text") if isinstance(first, dict) else getattr(first, "text", str(first))
    assert "[1] @d1" in text_content
    second = result[1]
    if isinstance(second, dict):
        image_b64 = second.get("base64", "")
    else:
        image_b64 = getattr(second, "base64", "")
    assert image_b64 != original_b64


@pytest.mark.asyncio
async def test_export_inspector_snapshot_fills_nth(session: DesktopSession) -> None:
    meta = SnapshotMeta(
        ref_count=1,
        app_name="App",
        window_title="Window",
        scope="foreground",
    )
    refs = {
        "d1": ElementRef(
            ref_id="d1",
            role="AXButton",
            name="Save",
            bbox=BBox(10, 10, 60, 30),
            backend_key="k1",
        )
    }
    shot = ActionResult(
        success=True,
        screenshot_base64=_jpeg_base64(),
        screenshot_size=(400, 300),
    )
    session.take_screenshot = AsyncMock(return_value=shot)  # type: ignore[method-assign]
    session._scaler = CoordinateScaler(
        screen_width=800,
        screen_height=600,
        sent_width=400,
        sent_height=300,
        dpi_scale=1.0,
    )

    with patch(
        "myrm_agent_harness.toolkits.computer_use.desktop_session.capture_snapshot",
        return_value=(meta, refs),
    ):
        payload = await session.export_inspector_snapshot()

    refs_payload = payload["refs"]
    assert isinstance(refs_payload, dict)
    assert refs_payload["d1"]["nth"] == 1


@pytest.mark.asyncio
async def test_desktop_snapshot_text_only_has_no_nth(session: DesktopSession) -> None:
    meta = SnapshotMeta(
        ref_count=1,
        app_name="App",
        window_title="Window",
        scope="foreground",
    )
    refs = {
        "d1": ElementRef(
            ref_id="d1",
            role="AXButton",
            name="OK",
            bbox=BBox(0, 0, 10, 10),
            backend_key="k1",
        )
    }
    emitted: list[dict[str, object]] = []

    async def _capture_sink(payload: dict[str, object]) -> None:
        emitted.append(payload)

    from myrm_agent_harness.utils.runtime import progress_sink

    class _Sink:
        async def emit(self, event: dict[str, object]) -> None:
            emitted.append(event)

    progress_sink.set_tool_progress_sink(_Sink())

    try:
        with patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.capture_snapshot",
            return_value=(meta, refs),
        ):
            result = await session.desktop_snapshot(include_screenshot=False)

        assert isinstance(result, str)
        assert "[1]" not in result
        assert len(emitted) == 1
        data = emitted[0]["data"]
        assert isinstance(data, dict)
        refs_data = data["refs"]
        assert isinstance(refs_data, dict)
        assert refs_data["d1"]["nth"] is None
    finally:
        progress_sink.set_tool_progress_sink(None)
