"""Tests for DesktopSession action lock serialization and structured error remedy hints."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.computer_use.desktop_session import DesktopSession
from myrm_agent_harness.toolkits.computer_use.dref.errors import DRefStaleError
from myrm_agent_harness.toolkits.computer_use.dref.types import ElementRef, SnapshotMeta
from myrm_agent_harness.toolkits.computer_use.types import ActionResult, ScreenInfo


@pytest.fixture
def mock_backend() -> MagicMock:
    backend = MagicMock()
    backend.screen_info.return_value = ScreenInfo(
        width=1920,
        height=1080,
        dpi_scale=1.0,
    )
    backend.is_browser_active = AsyncMock(return_value=False)
    backend.click = AsyncMock(return_value=ActionResult(success=True))
    backend.type_text = AsyncMock(return_value=ActionResult(success=True))
    return backend


@pytest.fixture
def mock_config() -> MagicMock:
    config = MagicMock()
    config.screenshot_delay = 0.0
    config.image_constraints = MagicMock()
    return config


def test_action_lock_initialization(mock_backend: MagicMock, mock_config: MagicMock) -> None:
    session = DesktopSession(backend=mock_backend, config=mock_config)
    assert hasattr(session, "_action_lock")
    assert isinstance(session._action_lock, asyncio.Lock)


@pytest.mark.asyncio
async def test_desktop_interact_serializes_concurrent_calls(
    mock_backend: MagicMock, mock_config: MagicMock
) -> None:
    session = DesktopSession(backend=mock_backend, config=mock_config)
    session._last_snapshot_time = time.time()
    meta = SnapshotMeta(ref_count=2, app_name="App", window_title="Window", scope="foreground")
    elem1 = ElementRef(ref_id="d1", role="button", name="Button 1", bbox=(10, 10, 50, 50), backend_key="k1")
    elem2 = ElementRef(ref_id="d2", role="button", name="Button 2", bbox=(60, 60, 100, 100), backend_key="k2")
    session._refs.replace({"d1": elem1, "d2": elem2}, meta)

    execution_order: list[str] = []

    def slow_invoke(backend, element, action, text, app_name=None):
        execution_order.append(f"start_{element.ref_id}")
        time.sleep(0.04)
        execution_order.append(f"end_{element.ref_id}")
        res = MagicMock()
        res.success = True
        return res

    with (
        patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.invoke_element",
            side_effect=slow_invoke,
        ),
        patch.object(session, "desktop_snapshot", AsyncMock(return_value="tree text")),
    ):
        res1, res2 = await asyncio.gather(
            session.desktop_interact(ref="d1", action="click"),
            session.desktop_interact(ref="d2", action="click"),
        )

        assert "Action 'click' on @d1 succeeded." in str(res1)
        assert "Action 'click' on @d2 succeeded." in str(res2)
        # Verify strict non-overlapping serialization: start_d1 -> end_d1 -> start_d2 -> end_d2
        assert execution_order == ["start_d1", "end_d1", "start_d2", "end_d2"]


@pytest.mark.asyncio
async def test_desktop_interact_and_vision_action_mutual_exclusion(
    mock_backend: MagicMock, mock_config: MagicMock
) -> None:
    session = DesktopSession(backend=mock_backend, config=mock_config)
    session._last_snapshot_time = time.time()
    meta = SnapshotMeta(ref_count=1, app_name="App", window_title="Window", scope="foreground")
    elem1 = ElementRef(ref_id="d1", role="button", name="Button 1", bbox=(10, 10, 50, 50), backend_key="k1")
    session._refs.replace({"d1": elem1}, meta)

    timeline: list[str] = []

    def slow_invoke(backend, element, action, text, app_name=None):
        timeline.append("interact_start")
        time.sleep(0.04)
        timeline.append("interact_end")
        res = MagicMock()
        res.success = True
        return res

    async def slow_click_at(*args, **kwargs):
        timeline.append("vision_start")
        await asyncio.sleep(0.04)
        timeline.append("vision_end")
        return ActionResult(success=True)

    session.click_at = slow_click_at  # type: ignore[assignment]

    with (
        patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.invoke_element",
            side_effect=slow_invoke,
        ),
        patch.object(session, "desktop_snapshot", AsyncMock(return_value="snapshot")),
    ):
        await asyncio.gather(
            session.desktop_interact(ref="d1", action="click"),
            session.desktop_vision_action(action="left_click", coordinate=[100, 100]),
        )

        assert timeline in (
            ["interact_start", "interact_end", "vision_start", "vision_end"],
            ["vision_start", "vision_end", "interact_start", "interact_end"],
        )


@pytest.mark.asyncio
async def test_stale_ref_returns_structured_remedy_hint(
    mock_backend: MagicMock, mock_config: MagicMock
) -> None:
    session = DesktopSession(backend=mock_backend, config=mock_config)
    session._last_snapshot_time = time.time()

    with patch.object(session._refs, "get", side_effect=DRefStaleError("Stale d99")):
        res = await session.desktop_interact(ref="d99", action="click")
        assert "Stale d99" in str(res)
        assert "[REMEDY_HINT:" in str(res)
        assert "desktop_snapshot_tool(scope='foreground')" in str(res)


@pytest.mark.asyncio
async def test_interact_failure_returns_structured_remedy_hint(
    mock_backend: MagicMock, mock_config: MagicMock
) -> None:
    session = DesktopSession(backend=mock_backend, config=mock_config)
    session._last_snapshot_time = time.time()
    meta = SnapshotMeta(ref_count=1, app_name="App", window_title="Window", scope="foreground")
    elem = ElementRef(ref_id="d1", role="button", name="Button", bbox=(10, 10, 50, 50), backend_key="k1")
    session._refs.replace({"d1": elem}, meta)

    mock_ax_result = MagicMock()
    mock_ax_result.success = False
    mock_ax_result.error = "AXElementNotFound"

    mock_bbox_result = MagicMock()
    mock_bbox_result.success = False
    mock_bbox_result.error = "BBoxClickFailed"

    with (
        patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.invoke_element",
            return_value=mock_ax_result,
        ),
        patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.try_bbox_click",
            AsyncMock(return_value=mock_bbox_result),
        ),
    ):
        res = await session.desktop_interact(ref="d1", action="click")
        assert "desktop_interact failed for @d1" in str(res)
        assert "AXElementNotFound" in str(res)
        assert "BBoxClickFailed" in str(res)
        assert "[REMEDY_HINT:" in str(res)
        assert "Suggested remedies:" in str(res)
