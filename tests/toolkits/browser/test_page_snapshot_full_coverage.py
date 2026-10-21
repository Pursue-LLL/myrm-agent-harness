"""Complete coverage tests for PageSnapshot error paths and edge cases."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.snapshot.page_snapshot import FrameRegistry


class TestPageSnapshotErrorPaths:
    """Test PageSnapshot error handling paths."""

    @pytest.mark.asyncio
    async def test_get_frame_snapshot_invalid_index(self) -> None:
        """Test _get_frame_snapshot with out-of-range frame index."""
        page = MagicMock()
        page.frames = [MagicMock(), MagicMock()]  # Only 2 frames

        page_snapshot = FrameRegistry(page)

        # Try to get frame index 10 (out of range)
        result = await page_snapshot._get_frame_snapshot(
            frame_index=10,
            force_full=False,
            cursor_interactive=False,
            selector="",
            scope="interactive",
            compact=False,
            max_depth=None,
        )

        # Should return error snapshot
        assert "Frame 10 not found" in result.tree
        assert len(result.refs) == 0

    @pytest.mark.asyncio
    async def test_create_frame_snapshot_out_of_range(self) -> None:
        """Test _create_frame_snapshot with frame_index >= len(frames)."""
        page = MagicMock()
        page.frames = [MagicMock()]  # Only 1 frame (index 0)

        page_snapshot = FrameRegistry(page)

        # Try to create snapshot for frame index 5 (out of range)
        result = await page_snapshot._create_frame_state(5)

        # Should return None
        assert result is None

    @pytest.mark.asyncio
    async def test_create_frame_snapshot_exception(self) -> None:
        """Test _create_frame_snapshot when FrameState() raises exception."""
        page = MagicMock()

        # Create a mock frame that will cause FrameSnapshot to fail
        bad_frame = MagicMock()
        page.frames = [bad_frame]

        page_snapshot = FrameRegistry(page)

        # Patch FrameState to raise exception
        from myrm_agent_harness.toolkits.browser.snapshot.frame_snapshot import FrameState

        original_init = FrameState.__init__

        def failing_init(self: object, frame: object) -> None:
            raise RuntimeError("FrameState init failed")

        FrameState.__init__ = failing_init
        try:
            result = await page_snapshot._create_frame_state(0)
            # Should return None when exception occurs
            assert result is None
        finally:
            FrameState.__init__ = original_init


class TestPageSnapshotMaxDepthIntegration:
    """Test max_depth parameter propagation in PageSnapshot."""

    @pytest.mark.asyncio
    async def test_capture_with_max_depth(self) -> None:
        """Test capture() passes max_depth to frame snapshots."""
        page = MagicMock()

        locator = MagicMock()
        locator.aria_snapshot = AsyncMock(
            return_value="""- button:
    name: Test
"""
        )
        page.locator = MagicMock(return_value=locator)
        page.frames = [page]
        page.evaluate = AsyncMock(return_value={})

        page_snapshot = FrameRegistry(page)

        aria_tree, refs, source = await page_snapshot.capture(scope="interactive", max_depth=5)

        assert aria_tree
        assert isinstance(refs, dict)
        assert isinstance(source, str)

    @pytest.mark.asyncio
    async def test_capture_without_max_depth(self) -> None:
        """Test capture() with max_depth=None (default)."""
        page = MagicMock()

        locator = MagicMock()
        locator.aria_snapshot = AsyncMock(
            return_value="""- button:
    name: Default
"""
        )
        page.locator = MagicMock(return_value=locator)
        page.frames = [page]
        page.evaluate = AsyncMock(return_value={})

        page_snapshot = FrameRegistry(page)

        aria_tree, _refs, source = await page_snapshot.capture(scope="interactive", max_depth=None)

        assert aria_tree
        assert "button" in aria_tree.lower()
        assert isinstance(source, str)
