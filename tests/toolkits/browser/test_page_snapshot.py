"""Unit tests for PageSnapshot"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.snapshot.aria_types import RefInfo
from myrm_agent_harness.toolkits.browser.snapshot.frame_snapshot import AriaSnapshot, SnapshotSource
from myrm_agent_harness.toolkits.browser.snapshot.page_snapshot import FrameRegistry


class TestPageSnapshot:
    """PageSnapshot 单元测试"""

    @pytest.mark.asyncio
    async def test_capture_main_frame_only(self):
        """测试只捕获主框架"""
        mock_page = MagicMock()
        mock_page.frames = [mock_page]

        with patch(
            "myrm_agent_harness.toolkits.browser.snapshot.page_snapshot.FrameState"
        ) as mock_frame_snapshot_class:
            mock_frame_snapshot = MagicMock()
            mock_frame_snapshot.capture = AsyncMock(
                return_value=AriaSnapshot(
                    tree="e0: button 'Click'",
                    refs={"e0": RefInfo("button", "Click", None)},
                    source=SnapshotSource.FULL,
                    timestamp=1234567890.0,
                    metrics=None,
                )
            )
            mock_frame_snapshot_class.return_value = mock_frame_snapshot

            page_snapshot = FrameRegistry(mock_page)
            aria_tree, refs, source = await page_snapshot.capture(include_iframes=False)

            assert aria_tree == "e0: button 'Click'"
            assert len(refs) == 1
            assert "e0" in refs
            assert source == SnapshotSource.FULL

    @pytest.mark.asyncio
    async def test_capture_with_iframes(self):
        """测试捕获主框架 + iframe"""
        mock_page = MagicMock()
        mock_iframe = MagicMock()
        mock_page.frames = [mock_page, mock_iframe]

        with patch(
            "myrm_agent_harness.toolkits.browser.snapshot.page_snapshot.FrameState"
        ) as mock_frame_snapshot_class:
            main_snapshot = AriaSnapshot(
                tree="e0: button 'Main'",
                refs={"e0": RefInfo("button", "Main", None)},
                source=SnapshotSource.FULL,
                timestamp=1234567890.0,
                metrics=None,
            )
            iframe_snapshot = AriaSnapshot(
                tree="e0: button 'Iframe'",
                refs={"e0": RefInfo("button", "Iframe", None)},
                source=SnapshotSource.FULL,
                timestamp=1234567890.0,
                metrics=None,
            )

            mock_frame_snapshot = MagicMock()
            mock_frame_snapshot.capture = AsyncMock(side_effect=[main_snapshot, iframe_snapshot])
            mock_frame_snapshot_class.return_value = mock_frame_snapshot

            page_snapshot = FrameRegistry(mock_page)
            aria_tree, refs, source = await page_snapshot.capture(include_iframes=True)

            assert "e0: button 'Main'" in aria_tree
            assert "e0: button 'Iframe'" in aria_tree
            assert "--- iframe 1 ---" in aria_tree
            assert len(refs) == 2
            assert "e0" in refs
            assert "f1_e0" in refs
            assert source == SnapshotSource.FULL

    @pytest.mark.asyncio
    async def test_capture_iframe_failure(self):
        """测试 iframe 捕获失败"""
        mock_page = MagicMock()
        mock_iframe = MagicMock()
        mock_page.frames = [mock_page, mock_iframe]

        with patch(
            "myrm_agent_harness.toolkits.browser.snapshot.page_snapshot.FrameState"
        ) as mock_frame_snapshot_class:
            main_snapshot = AriaSnapshot(
                tree="e0: button 'Main'",
                refs={"e0": RefInfo("button", "Main", None)},
                source=SnapshotSource.FULL,
                timestamp=1234567890.0,
                metrics=None,
            )

            mock_frame_snapshot = MagicMock()
            mock_frame_snapshot.capture = AsyncMock(side_effect=[main_snapshot, Exception("Failed")])
            mock_frame_snapshot_class.return_value = mock_frame_snapshot

            page_snapshot = FrameRegistry(mock_page)
            aria_tree, refs, source = await page_snapshot.capture(include_iframes=True)

            assert "e0: button 'Main'" in aria_tree
            assert "--- iframe 1 (failed:" in aria_tree
            assert len(refs) == 1
            assert source == "full"

    @pytest.mark.asyncio
    async def test_capture_with_selector(self):
        """测试 selector 参数传递"""
        mock_page = MagicMock()
        mock_page.frames = [mock_page]

        with patch(
            "myrm_agent_harness.toolkits.browser.snapshot.page_snapshot.FrameState"
        ) as mock_frame_snapshot_class:
            mock_frame_snapshot = MagicMock()
            mock_frame_snapshot.capture = AsyncMock(
                return_value=AriaSnapshot(
                    tree="e0: button 'Submit'",
                    refs={"e0": RefInfo("button", "Submit", None)},
                    source=SnapshotSource.FULL,
                    timestamp=1234567890.0,
                    metrics=None,
                )
            )
            mock_frame_snapshot_class.return_value = mock_frame_snapshot

            page_snapshot = FrameRegistry(mock_page)
            await page_snapshot.capture(selector="#form")

        mock_frame_snapshot.capture.assert_called_with(
            force_full=False,
            cursor_interactive=False,
            selector="#form",
            scope="interactive",
            compact=False,
            max_depth=None,
            max_tokens=0,
        )

    @pytest.mark.asyncio
    async def test_cleanup_stale_frames(self):
        """测试清理失效 Frame"""
        mock_page = MagicMock()
        mock_page.frames = [mock_page]

        with patch(
            "myrm_agent_harness.toolkits.browser.snapshot.page_snapshot.FrameState"
        ) as mock_frame_snapshot_class:
            mock_frame_snapshot = MagicMock()
            mock_frame_snapshot.capture = AsyncMock(
                return_value=AriaSnapshot(
                    tree="e0: button 'Click'",
                    refs={"e0": RefInfo("button", "Click", None)},
                    source=SnapshotSource.FULL,
                    timestamp=1234567890.0,
                    metrics=None,
                )
            )
            mock_frame_snapshot.cleanup = AsyncMock()
            mock_frame_snapshot_class.return_value = mock_frame_snapshot

            page_snapshot = FrameRegistry(mock_page)
            await page_snapshot.capture()

            page_snapshot._frame_states[2] = mock_frame_snapshot

            await page_snapshot.cleanup_stale_frames()

            assert 0 in page_snapshot._frame_states
            assert 2 not in page_snapshot._frame_states
            mock_frame_snapshot.cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_reset(self):
        """测试重置"""
        mock_page = MagicMock()
        mock_page.frames = [mock_page]

        with patch(
            "myrm_agent_harness.toolkits.browser.snapshot.page_snapshot.FrameState"
        ) as mock_frame_snapshot_class:
            mock_frame_snapshot = MagicMock()
            mock_frame_snapshot.capture = AsyncMock(
                return_value=AriaSnapshot(
                    tree="e0: button 'Click'",
                    refs={"e0": RefInfo("button", "Click", None)},
                    source=SnapshotSource.FULL,
                    timestamp=1234567890.0,
                    metrics=None,
                )
            )
            mock_frame_snapshot.reset = MagicMock()
            mock_frame_snapshot_class.return_value = mock_frame_snapshot

            page_snapshot = FrameRegistry(mock_page)
            await page_snapshot.capture()

            page_snapshot.reset()

            mock_frame_snapshot.reset.assert_called_once()
            assert len(page_snapshot._frame_states) == 0

    def test_error_snapshot(self):
        """测试错误快照"""
        from myrm_agent_harness.toolkits.browser.snapshot.snapshot_types import AriaSnapshot

        result = AriaSnapshot.create_error("Test error")

        assert result.tree == "Test error"
        assert len(result.refs) == 0
        assert result.source == "full"

    def test_stats(self):
        """测试统计信息"""
        mock_page = MagicMock()
        page_snapshot = FrameRegistry(mock_page)

        stats = page_snapshot.stats

        assert stats["total_frames"] == 0
        assert stats["frame_stats"] == {}
