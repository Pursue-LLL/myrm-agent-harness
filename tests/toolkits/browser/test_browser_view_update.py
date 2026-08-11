"""Tests for BrowserSession BROWSER_VIEW_UPDATE SSE emission (BLCV)."""

from __future__ import annotations

from typing import ClassVar
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.core.events.types import AgentEventType
from myrm_agent_harness.toolkits.browser.snapshot import RefInfo, SnapshotMeta
from myrm_agent_harness.utils.runtime import progress_sink


class _CaptureSink:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def emit(self, event: dict[str, object]) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_publish_inspector_view_emits_browser_view_update() -> None:
    from myrm_agent_harness.toolkits.browser.session.browser_session_view_mixin import (
        BrowserSessionViewMixin,
    )

    class _Session(BrowserSessionViewMixin):
        _view_emit_last_monotonic = 0.0

        async def _ensure_components(self) -> None:
            return None

    session = _Session()
    sink = _CaptureSink()
    progress_sink.set_tool_progress_sink(sink)

    payload = {
        "screenshot_base64": "abc",
        "mime_type": "image/jpeg",
        "refs": {},
        "page_url": "https://example.com",
        "page_title": "Example",
        "viewport_width": 1280,
        "viewport_height": 720,
    }

    try:
        with patch(
            "myrm_agent_harness.toolkits.browser.session.view_update_payload.capture_browser_view_update_data",
            new=AsyncMock(return_value=payload),
        ):
            await session._publish_inspector_view(force=True)

        assert len(sink.events) == 1
        assert sink.events[0]["type"] == AgentEventType.BROWSER_VIEW_UPDATE.value
        assert sink.events[0]["data"] == payload
    finally:
        progress_sink.set_tool_progress_sink(None)


@pytest.mark.asyncio
async def test_publish_inspector_view_throttles_rapid_emits() -> None:
    from myrm_agent_harness.toolkits.browser.session.browser_session_view_mixin import (
        BrowserSessionViewMixin,
    )

    class _Session(BrowserSessionViewMixin):
        _view_emit_last_monotonic = 0.0

        async def _ensure_components(self) -> None:
            return None

    session = _Session()
    sink = _CaptureSink()
    progress_sink.set_tool_progress_sink(sink)
    payload = {
        "screenshot_base64": "abc",
        "mime_type": "image/jpeg",
        "refs": {},
        "page_url": "https://example.com",
        "page_title": "Example",
        "viewport_width": 1280,
        "viewport_height": 720,
    }

    try:
        with patch(
            "myrm_agent_harness.toolkits.browser.session.view_update_payload.capture_browser_view_update_data",
            new=AsyncMock(return_value=payload),
        ):
            await session._publish_inspector_view(force=True)
            await session._publish_inspector_view(force=False)

        assert len(sink.events) == 1
    finally:
        progress_sink.set_tool_progress_sink(None)


@pytest.mark.asyncio
async def test_capture_snapshot_skips_nested_inspector_publish() -> None:
    from myrm_agent_harness.toolkits.browser.session.view_update_payload import (
        capture_browser_view_update_data,
    )

    class _FakeSession:
        snapshot_calls = 0
        publish_flags: ClassVar[list[bool]] = []

        async def snapshot(self, **kwargs: object) -> object:
            self.snapshot_calls += 1
            self.publish_flags.append(bool(kwargs.get("publish_inspector_view", True)))
            meta = SnapshotMeta(ref_count=0, estimated_tokens=0)
            from types import MappingProxyType

            from myrm_agent_harness.toolkits.browser.session.snapshot_result import SnapshotResult

            return SnapshotResult(
                aria_tree="tree",
                refs=MappingProxyType({}),
                meta=meta,
                is_incremental=False,
            )

        async def extract_screenshot(self, *, scale: float = 1.0) -> str:
            return "img"

        _tab_controller = None

    session = _FakeSession()
    with patch(
        "myrm_agent_harness.toolkits.browser.session.browser_session.BrowserSession",
        _FakeSession,
    ):
        await capture_browser_view_update_data(session)

    assert session.snapshot_calls == 1
    assert session.publish_flags == [False]


def test_build_browser_view_update_data_shape() -> None:
    from myrm_agent_harness.toolkits.browser.session.view_update_payload import (
        build_browser_view_update_data,
        refs_data_from_ref_map,
    )

    refs = refs_data_from_ref_map(
        {
            "e1": RefInfo(
                role="button",
                name="Submit",
                nth=0,
                bbox=None,
                position=None,
            )
        }
    )
    data = build_browser_view_update_data(
        screenshot_base64="img",
        refs_data=refs,
        page_url="https://example.com",
        page_title="Example",
    )
    assert data["screenshot_base64"] == "img"
    assert data["page_url"] == "https://example.com"
    assert "e1" in data["refs"]

    from myrm_agent_harness.toolkits.browser.session.view_update_payload import (
        build_browser_view_update_data,
        refs_data_from_ref_map,
    )

    refs = refs_data_from_ref_map(
        {
            "e1": RefInfo(
                role="button",
                name="Submit",
                nth=0,
                bbox=None,
                position=None,
            )
        }
    )
    data = build_browser_view_update_data(
        screenshot_base64="img",
        refs_data=refs,
        page_url="https://example.com",
        page_title="Example",
    )
    assert data["screenshot_base64"] == "img"
    assert data["page_url"] == "https://example.com"
    assert "e1" in data["refs"]
