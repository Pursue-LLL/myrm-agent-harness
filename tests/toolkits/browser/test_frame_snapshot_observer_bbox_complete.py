"""Complete coverage tests for FrameSnapshot observer and bbox methods.

Tests for observer management and bbox collection functionality.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.snapshot.element_detectors import collect_bboxes, detect_cursor_interactive
from myrm_agent_harness.toolkits.browser.snapshot.frame_snapshot import FrameState


class TestFrameSnapshotObserverCoverage:
    """Test observer-related methods."""

    @pytest.fixture
    def mock_frame_with_observer(self) -> MagicMock:
        """Create mock frame for observer tests."""
        frame = MagicMock()
        frame.url = "https://example.com"
        frame.evaluate = AsyncMock(return_value=None)

        locator = MagicMock()
        locator.aria_snapshot = AsyncMock(
            return_value="""- button:
    name: Test
"""
        )
        frame.locator = MagicMock(return_value=locator)

        return frame

    @pytest.mark.asyncio
    async def test_install_observer_success(self, mock_frame_with_observer: MagicMock) -> None:
        """Test observer successful installation."""
        snapshot_manager = FrameState(mock_frame_with_observer)

        await snapshot_manager._observer.install()

        assert snapshot_manager._observer.is_installed is True
        mock_frame_with_observer.evaluate.assert_called_once()

    @pytest.mark.asyncio
    async def test_install_observer_failure(self, mock_frame_with_observer: MagicMock) -> None:
        """Test observer when installation fails."""
        mock_frame_with_observer.evaluate = AsyncMock(side_effect=Exception("Install failed"))

        snapshot_manager = FrameState(mock_frame_with_observer)
        await snapshot_manager._observer.install()

        assert snapshot_manager._observer.is_installed is False

    @pytest.mark.asyncio
    async def test_get_changes_success(self, mock_frame_with_observer: MagicMock) -> None:
        """Test get_changes when observer returns changes."""
        mock_frame_with_observer.evaluate = AsyncMock(return_value=["change1", "change2"])

        snapshot_manager = FrameState(mock_frame_with_observer)
        changes = await snapshot_manager._observer.get_changes()

        assert len(changes) == 2
        assert changes[0] == "change1"

    @pytest.mark.asyncio
    async def test_get_changes_no_observer(self, mock_frame_with_observer: MagicMock) -> None:
        """Test get_changes when observer returns None."""
        mock_frame_with_observer.evaluate = AsyncMock(return_value=None)

        snapshot_manager = FrameState(mock_frame_with_observer)
        changes = await snapshot_manager._observer.get_changes()

        assert changes == []

    @pytest.mark.asyncio
    async def test_get_changes_failure(self, mock_frame_with_observer: MagicMock) -> None:
        """Test get_changes when evaluate throws error."""
        mock_frame_with_observer.evaluate = AsyncMock(side_effect=Exception("Eval failed"))

        snapshot_manager = FrameState(mock_frame_with_observer)
        changes = await snapshot_manager._observer.get_changes()

        assert changes == []

    @pytest.mark.asyncio
    async def test_detect_cursor_interactive_success(self, mock_frame_with_observer: MagicMock) -> None:
        """Test detect_cursor_interactive when elements found."""
        mock_frame_with_observer.evaluate = AsyncMock(
            return_value=[{"role": "custom", "name": "Element", "text": "Text"}]
        )

        elements = await detect_cursor_interactive(mock_frame_with_observer)

        assert len(elements) == 1
        assert elements[0]["name"] == "Element"

    @pytest.mark.asyncio
    async def test_detect_cursor_interactive_failure(self, mock_frame_with_observer: MagicMock) -> None:
        """Test detect_cursor_interactive when script fails."""
        mock_frame_with_observer.evaluate = AsyncMock(side_effect=Exception("Script failed"))

        elements = await detect_cursor_interactive(mock_frame_with_observer)

        assert elements == []

    @pytest.mark.asyncio
    async def test_detect_cursor_interactive_invalid_return(self, mock_frame_with_observer: MagicMock) -> None:
        """Test detect_cursor_interactive with invalid return type."""
        mock_frame_with_observer.evaluate = AsyncMock(return_value="not a list")

        elements = await detect_cursor_interactive(mock_frame_with_observer)

        assert elements == []


class TestFrameSnapshotBBoxCoverage:
    """Test bbox collection methods."""

    @pytest.fixture
    def mock_frame_bbox(self) -> MagicMock:
        """Create mock frame for bbox tests."""
        frame = MagicMock()
        frame.url = "https://example.com"

        locator = MagicMock()
        locator.aria_snapshot = AsyncMock(
            return_value="""- button:
    name: Test
- link:
    name: Home
"""
        )
        frame.locator = MagicMock(return_value=locator)

        frame.evaluate = AsyncMock(
            return_value={
                "button:Test": {
                    "x": 10,
                    "y": 20,
                    "width": 100,
                    "height": 50,
                    "centerX": 60,
                    "centerY": 45,
                    "viewport": {"width": 1920, "height": 1080},
                }
            }
        )

        return frame

    @pytest.mark.asyncio
    async def test_collect_bboxes_success(self, mock_frame_bbox: MagicMock) -> None:
        """Test collect_bboxes successful collection."""
        aria_yaml = await mock_frame_bbox.locator().aria_snapshot()
        bbox_map = await collect_bboxes(mock_frame_bbox, aria_yaml)

        assert "button:Test" in bbox_map
        assert bbox_map["button:Test"]["centerX"] == 60

    @pytest.mark.asyncio
    async def test_collect_bboxes_script_failure(self, mock_frame_bbox: MagicMock) -> None:
        """Test collect_bboxes when evaluate fails."""
        mock_frame_bbox.evaluate = AsyncMock(side_effect=Exception("Script error"))

        aria_yaml = await mock_frame_bbox.locator().aria_snapshot()
        bbox_map = await collect_bboxes(mock_frame_bbox, aria_yaml)

        assert bbox_map == {}

    @pytest.mark.asyncio
    async def test_collect_bboxes_invalid_return_type(self, mock_frame_bbox: MagicMock) -> None:
        """Test collect_bboxes with invalid return type."""
        mock_frame_bbox.evaluate = AsyncMock(return_value="not a dict")

        aria_yaml = await mock_frame_bbox.locator().aria_snapshot()
        bbox_map = await collect_bboxes(mock_frame_bbox, aria_yaml)

        assert bbox_map == {}

    @pytest.mark.asyncio
    async def test_collect_bboxes_empty_aria_tree(self, mock_frame_bbox: MagicMock) -> None:
        """Test collect_bboxes with empty ARIA tree."""
        bbox_map = await collect_bboxes(mock_frame_bbox, "")

        assert bbox_map == {}

    @pytest.mark.asyncio
    async def test_collect_bboxes_parse_error(self, mock_frame_bbox: MagicMock) -> None:
        """Test collect_bboxes when YAML parsing fails."""
        bbox_map = await collect_bboxes(mock_frame_bbox, "- button: [unclosed")

        assert bbox_map == {}
