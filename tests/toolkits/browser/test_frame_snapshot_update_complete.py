"""Complete coverage tests for FrameSnapshot full update logic.

Tests the _full_update method and related snapshot generation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.snapshot.frame_snapshot import FrameState


class TestFrameSnapshotFullCoverage:
    """Complete coverage for FrameSnapshot._full_update and integration."""

    @pytest.fixture
    def mock_frame(self) -> MagicMock:
        """Create a mock Frame with locator support."""
        frame = MagicMock()
        frame.url = "https://example.com"

        locator = MagicMock()
        locator.aria_snapshot = AsyncMock(
            return_value="""- WebArea:
    name: Test Page
    children:
      - button:
          name: Submit
      - link:
          name: Home
"""
        )
        frame.locator = MagicMock(return_value=locator)

        frame.evaluate = AsyncMock(
            return_value={
                "button:Submit": {
                    "x": 100,
                    "y": 200,
                    "width": 80,
                    "height": 40,
                    "centerX": 140,
                    "centerY": 220,
                    "viewport": {"width": 1920, "height": 1080},
                },
                "link:Home": {
                    "x": 300,
                    "y": 400,
                    "width": 60,
                    "height": 30,
                    "centerX": 330,
                    "centerY": 415,
                    "viewport": {"width": 1920, "height": 1080},
                },
            }
        )

        return frame

    @pytest.mark.asyncio
    async def test_full_update_with_max_depth(self, mock_frame: MagicMock) -> None:
        """Test _full_update with max_depth parameter."""
        snapshot_manager = FrameState(mock_frame)

        result = await snapshot_manager.capture(scope="interactive", max_depth=3)

        assert result.tree
        assert result.refs
        assert len(result.refs) >= 2

    @pytest.mark.asyncio
    async def test_full_update_acquisition_error(self, mock_frame: MagicMock) -> None:
        """Test _full_update when ARIA acquisition fails."""
        mock_frame.locator().aria_snapshot = AsyncMock(side_effect=Exception("Locator failed"))

        snapshot_manager = FrameState(mock_frame)
        from myrm_agent_harness.toolkits.browser.exceptions import AriaAcquisitionError

        with pytest.raises(AriaAcquisitionError, match="Failed to acquire ARIA tree"):
            await snapshot_manager.capture(scope="interactive")

    @pytest.mark.asyncio
    async def test_full_update_parse_error(self, mock_frame: MagicMock) -> None:
        """Test _full_update when YAML parsing fails."""
        mock_frame.locator().aria_snapshot = AsyncMock(return_value="invalid: [yaml")

        snapshot_manager = FrameState(mock_frame)
        from myrm_agent_harness.toolkits.browser.exceptions import AriaParseError

        with pytest.raises(AriaParseError, match="Failed to parse ARIA YAML"):
            await snapshot_manager.capture(scope="interactive")

    @pytest.mark.asyncio
    async def test_full_update_with_selector(self, mock_frame: MagicMock) -> None:
        """Test _full_update with CSS selector."""
        snapshot_manager = FrameState(mock_frame)

        result = await snapshot_manager.capture(scope="interactive", selector=".main-content")

        mock_frame.locator.assert_called()
        assert result.tree

    @pytest.mark.asyncio
    async def test_full_update_with_cursor_interactive(self) -> None:
        """Test _full_update with cursor_interactive enabled."""
        frame = MagicMock()
        frame.url = "https://example.com"

        locator = MagicMock()
        locator.aria_snapshot = AsyncMock(
            return_value="""- button:
    name: Submit
"""
        )
        frame.locator = MagicMock(return_value=locator)

        call_count = 0

        async def mock_evaluate(script: str, *args: object, **kwargs: object) -> object:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {}
            else:
                return [
                    {"role": "cursor-interactive", "name": "Custom Element", "text": "Click me"},
                ]

        frame.evaluate = mock_evaluate

        snapshot_manager = FrameState(frame)
        result = await snapshot_manager.capture(scope="interactive", cursor_interactive=True)

        assert result.tree
        assert "cursor-interactive" in result.tree
        assert "Custom Element" in result.tree

    @pytest.mark.asyncio
    async def test_full_update_cursor_interactive_no_elements(self, mock_frame: MagicMock) -> None:
        """Test cursor_interactive when no custom elements found."""
        mock_frame.evaluate = AsyncMock(
            side_effect=[
                {},
                [],
            ]
        )

        snapshot_manager = FrameState(mock_frame)
        result = await snapshot_manager.capture(scope="interactive", cursor_interactive=True)

        assert result.tree
        assert "cursor-interactive" not in result.tree

    @pytest.mark.asyncio
    async def test_full_update_cursor_interactive_duplicate_names(self, mock_frame: MagicMock) -> None:
        """Test cursor_interactive with duplicate names (should skip)."""
        mock_frame.evaluate = AsyncMock(
            side_effect=[
                {
                    "button:Submit": {
                        "x": 100,
                        "y": 200,
                        "width": 80,
                        "height": 40,
                        "centerX": 140,
                        "centerY": 220,
                        "viewport": {"width": 1920, "height": 1080},
                    }
                },
                [{"role": "cursor-interactive", "name": "Submit", "text": "Submit"}],
            ]
        )

        snapshot_manager = FrameState(mock_frame)
        result = await snapshot_manager.capture(scope="interactive", cursor_interactive=True)

        cursor_refs = [ref for ref in result.refs.values() if ref.role == "cursor-interactive"]
        assert len(cursor_refs) == 0

    @pytest.mark.asyncio
    async def test_full_update_bbox_collection_failure(self, mock_frame: MagicMock) -> None:
        """Test _full_update when bbox collection fails."""
        mock_frame.evaluate = AsyncMock(side_effect=Exception("BBox script failed"))

        snapshot_manager = FrameState(mock_frame)
        result = await snapshot_manager.capture(scope="interactive")

        assert result.tree
        assert result.refs
        for ref in result.refs.values():
            assert ref.position is None

    @pytest.mark.asyncio
    async def test_full_update_all_scopes(self, mock_frame: MagicMock) -> None:
        """Test _full_update with all scope values."""
        snapshot_manager = FrameState(mock_frame)

        result_int = await snapshot_manager.capture(scope="interactive")
        refs_int = len(result_int.refs)

        result_con = await snapshot_manager.capture(scope="content")
        refs_con = len(result_con.refs)

        result_full = await snapshot_manager.capture(scope="full")
        refs_full = len(result_full.refs)

        assert refs_full >= refs_con >= refs_int

    @pytest.mark.asyncio
    async def test_full_update_compact_mode(self, mock_frame: MagicMock) -> None:
        """Test _full_update with compact mode."""
        snapshot_manager = FrameState(mock_frame)

        result = await snapshot_manager.capture(scope="interactive", compact=True)

        assert result.tree
        assert "e0:" in result.tree or "button" in result.tree.lower()

    @pytest.mark.asyncio
    async def test_full_update_caching(self, mock_frame: MagicMock) -> None:
        """Test that _full_update updates internal cache."""
        snapshot_manager = FrameState(mock_frame)

        result1 = await snapshot_manager.capture(scope="interactive")

        assert snapshot_manager._cached_aria_tree is not None
        assert snapshot_manager._cached_refs is not None
        assert len(snapshot_manager._cached_refs) == len(result1.refs)

    @pytest.mark.asyncio
    async def test_full_update_stats_tracking(self, mock_frame: MagicMock) -> None:
        """Test that _full_update increments stats correctly."""
        snapshot_manager = FrameState(mock_frame)

        initial_full_updates = snapshot_manager._full_updates

        await snapshot_manager.capture(scope="interactive")

        assert snapshot_manager._full_updates == initial_full_updates + 1
