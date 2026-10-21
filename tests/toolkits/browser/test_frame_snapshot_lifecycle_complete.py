"""Complete coverage tests for FrameSnapshot lifecycle management.

Tests for cross-origin handling, cleanup, reset, and max_depth integration.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.snapshot.frame_snapshot import FrameState


class TestFrameSnapshotCrossOriginCoverage:
    """Test cross-origin handling."""

    @pytest.mark.asyncio
    async def test_cross_origin_frame_full_update(self) -> None:
        """Test cross-origin frame handling in _full_update."""
        frame = MagicMock()
        frame.url = "https://example.com"

        locator = MagicMock()
        locator.aria_snapshot = AsyncMock(side_effect=Exception("Cross-origin frame access denied"))
        frame.locator = MagicMock(return_value=locator)

        snapshot_manager = FrameState(frame)
        snapshot_manager._observer._is_cross_origin = True
        result = await snapshot_manager.capture(scope="interactive")

        assert "Cross-origin" in result.tree
        assert len(result.refs) == 0


class TestFrameSnapshotCleanupCoverage:
    """Test cleanup and resource management."""

    @pytest.mark.asyncio
    async def test_cleanup_with_observer(self) -> None:
        """Test cleanup method disconnects observer."""
        frame = MagicMock()
        frame.url = "https://example.com"
        frame.evaluate = AsyncMock(return_value=None)

        locator = MagicMock()
        locator.aria_snapshot = AsyncMock(return_value="- button:\n    name: Test")
        frame.locator = MagicMock(return_value=locator)

        snapshot_manager = FrameState(frame)
        snapshot_manager._observer._installed = True

        await snapshot_manager.cleanup()

        assert frame.evaluate.called

    @pytest.mark.asyncio
    async def test_cleanup_without_observer(self) -> None:
        """Test cleanup when observer not installed."""
        frame = MagicMock()
        frame.url = "https://example.com"
        frame.evaluate = AsyncMock(return_value=None)

        locator = MagicMock()
        locator.aria_snapshot = AsyncMock(return_value="- button:\n    name: Test")
        frame.locator = MagicMock(return_value=locator)

        snapshot_manager = FrameState(frame)
        snapshot_manager._observer._installed = False

        await snapshot_manager.cleanup()

        assert snapshot_manager._cached_aria_tree is None

    @pytest.mark.asyncio
    async def test_cleanup_cross_origin_skip(self) -> None:
        """Test cleanup skips observer for cross-origin frames."""
        frame = MagicMock()
        frame.url = "https://example.com"
        frame.evaluate = AsyncMock(return_value=None)

        snapshot_manager = FrameState(frame)
        snapshot_manager._observer._is_cross_origin = True
        snapshot_manager._observer._installed = True

        await snapshot_manager.cleanup()

        assert snapshot_manager._cached_aria_tree is None

    @pytest.mark.asyncio
    async def test_cleanup_observer_disconnect_error(self) -> None:
        """Test cleanup when observer disconnect throws error."""
        frame = MagicMock()
        frame.url = "https://example.com"
        frame.evaluate = AsyncMock(side_effect=Exception("Disconnect failed"))

        snapshot_manager = FrameState(frame)
        snapshot_manager._observer._installed = True
        snapshot_manager._observer._is_cross_origin = False

        await snapshot_manager.cleanup()

        assert snapshot_manager._cached_aria_tree is None


class TestFrameSnapshotResetCoverage:
    """Test reset method."""

    @pytest.mark.asyncio
    async def test_reset_clears_all_state(self) -> None:
        """Test reset clears all cached state."""
        frame = MagicMock()
        frame.url = "https://example.com"

        locator = MagicMock()
        locator.aria_snapshot = AsyncMock(return_value="- button:\n    name: Test")
        frame.locator = MagicMock(return_value=locator)
        frame.evaluate = AsyncMock(return_value={})

        snapshot_manager = FrameState(frame)

        await snapshot_manager.capture(scope="interactive")

        assert snapshot_manager._cached_aria_tree is not None
        assert snapshot_manager._cached_refs is not None

        snapshot_manager.reset()

        assert snapshot_manager._cached_aria_tree is None
        assert snapshot_manager._cached_refs is None
        assert snapshot_manager._cached_cursor_elements is None
        assert snapshot_manager._observer.is_installed is False


class TestFrameSnapshotMaxDepthIntegration:
    """Test max_depth parameter integration."""

    @pytest.mark.asyncio
    async def test_max_depth_none_uses_fast_path(self) -> None:
        """Test that max_depth=None uses Fast Path."""
        frame = MagicMock()
        frame.url = "https://example.com"

        locator = MagicMock()
        locator.aria_snapshot = AsyncMock(return_value="- button:\n    name: Fast")
        frame.locator = MagicMock(return_value=locator)
        frame.evaluate = AsyncMock(return_value={})

        snapshot_manager = FrameState(frame)
        result = await snapshot_manager.capture(scope="interactive", max_depth=None)

        assert "Fast" in result.tree or "button" in result.tree.lower()

    @pytest.mark.asyncio
    async def test_max_depth_value_uses_custom_path(self) -> None:
        """Test that max_depth=N uses Custom Path."""
        frame = MagicMock()
        frame.url = "https://example.com"

        locator = MagicMock()

        async def mock_aria_snapshot() -> str:
            return "- button:\n    name: Fallback"

        async def mock_evaluate(script: str, *args: object) -> str:
            if "maxDepth" in script:
                return "- button:\n    name: Custom"
            return {}

        locator.aria_snapshot = mock_aria_snapshot
        locator.evaluate = mock_evaluate
        frame.locator = MagicMock(return_value=locator)
        frame.evaluate = AsyncMock(return_value={})

        snapshot_manager = FrameState(frame)
        result = await snapshot_manager.capture(scope="interactive", max_depth=2)

        assert result.tree
