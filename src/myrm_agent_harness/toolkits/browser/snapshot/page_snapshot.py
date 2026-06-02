"""Multi-frame aggregate snapshot manager.


[INPUT]
- patchright.async_api::Page (POS: Patchright page instance)
- snapshot.frame_snapshot::FrameState (POS: single-frame state manager)
- snapshot.frame_snapshot::AriaSnapshot (POS: snapshot result dataclass)
- snapshot.aria_types::RefInfo (POS: element ref metadata)

[OUTPUT]
- FrameRegistry: multi-frame registry manager
- capture() returns: (aria_tree, refs, source) tuple

[POS]
Multi-frame registry manager. Responsibilities:
1. Lazily creates FrameState instances
2. Automatically cleans up stale frames
3. Coordinates snapshot capture between main frame and iframes
4. Handles iframe ref prefixes (f1_e0, f2_e1)
5. Aggregates snapshot source status (full update if any frame is fully updated)
6. Lifecycle management (reset after navigation)
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from .frame_snapshot import AriaSnapshot, FrameState, SnapshotSource

if TYPE_CHECKING:
    from patchright.async_api import Page

    from .aria_types import RefInfo

logger = logging.getLogger(__name__)


class FrameRegistry:
    """多 Frame Register管理器

    协调multiple FrameState Instance,provides统一 多 Frame SnapshotInterface:
    - lazy loading:只 in 首次访问时Create FrameState
    - 失效检测:AutoClean up already Delete  Frame
    - 生命周期管理:导航后AutoReset
    - iframe refs Prefix:f1_e0, f2_e1 Format
    - cursor-interactive 检测:传递 to All Frame
    - Snapshot来源聚合:任一 Frame 全量Update则整体 is 全量
    """

    def __init__(self, page: Page):
        """Initialize多 Frame Register管理器

        Args:
            page: Patchright Page Instance
        """
        self._page = page
        self._frame_states: dict[int, FrameState] = {}

    async def capture(
        self,
        include_iframes: bool = True,
        force_full: bool = False,
        cursor_interactive: bool = False,
        selector: str = "",
        scope: str = "interactive",
        compact: bool = False,
        max_depth: int | None = None,
        include_bbox: bool = False,
        max_tokens: int = 0,
    ) -> tuple[str, dict[str, RefInfo], str]:
        """捕获completePageSnapshot(主框架 + iframe)

        Args:
            include_iframes: WhetherContains iframe Content
            force_full: 强制全量Update
            cursor_interactive: 检测 cursor:pointer  etc.可交互Element
            selector: CSS 选择器(限定SnapshotRange)
            max_depth: Optional depth limit (None = Fast Path, int = Custom Path)
            scope: SnapshotRange(interactive/content/full)
            compact: 紧凑Format(节省 30% token)
            include_bbox: 收集 bbox Data(Debug ModeAuto启用)
            max_tokens: 最大 token 限制，0 表示不限制

        Returns:
            (aria_tree, refs, source) 元组,refs  in  iframe   key Format is  f{i}_{ref_id}
        """
        main_snapshot = await self._get_frame_snapshot(
            frame_index=0,
            force_full=force_full,
            cursor_interactive=cursor_interactive,
            selector=selector,
            scope=scope,
            compact=compact,
            max_depth=max_depth,
            include_bbox=include_bbox,
            max_tokens=max_tokens,
        )
        aria_tree = main_snapshot.tree
        refs = dict(main_snapshot.refs)
        source = main_snapshot.source

        if include_iframes:
            iframe_count = len(self._page.frames) - 1
            if iframe_count > 0:
                logger.info(f"Processing {iframe_count} iframes in parallel")

                iframe_tasks = [
                    self._get_frame_snapshot(
                        frame_index=i,
                        force_full=force_full,
                        cursor_interactive=cursor_interactive,
                        scope=scope,
                        compact=compact,
                        include_bbox=include_bbox,
                        max_depth=max_depth,
                        max_tokens=max_tokens,
                    )
                    for i in range(1, len(self._page.frames))
                ]

                iframe_results = await asyncio.gather(*iframe_tasks, return_exceptions=True)

                for i, result in enumerate(iframe_results, start=1):
                    if isinstance(result, Exception):
                        logger.warning(f"Failed to process iframe {i}: {result}")
                        aria_tree += f"\n\n--- iframe {i} (failed: {result}) ---"
                        source = SnapshotSource.FULL
                    else:
                        aria_tree += f"\n\n--- iframe {i} ---\n{result.tree}"

                        for ref_id, ref_info in result.refs.items():
                            refs[f"f{i}_{ref_id}"] = ref_info

                        if result.source == SnapshotSource.FULL:
                            source = SnapshotSource.FULL

        return aria_tree, refs, source

    async def _get_frame_snapshot(
        self,
        frame_index: int,
        force_full: bool,
        cursor_interactive: bool = False,
        selector: str = "",
        scope: str = "interactive",
        compact: bool = False,
        max_depth: int | None = None,
        include_bbox: bool = False,
        max_tokens: int = 0,
    ) -> AriaSnapshot:
        """Get指定 Frame  Snapshot(lazy loading)

        Args:
            frame_index: Frame Index(0=主框架,1+=iframe)
            force_full: 强制全量Update
            cursor_interactive: 检测 cursor:pointer Element
            selector: CSS 选择器(限定SnapshotRange)
            scope: SnapshotRange(interactive/content/full)
            compact: 紧凑Format(节省 30% token)
            max_depth: Optional depth limit (None = Fast Path, int = Custom Path)
            include_bbox: 收集 bbox Data(Debug ModeAuto启用)
            max_tokens: 最大 token 限制，0 表示不限制

        Returns:
            AriaSnapshot SnapshotResult
        """
        if frame_index not in self._frame_states:
            frame_state = await self._create_frame_state(frame_index)
            if frame_state is None:
                return AriaSnapshot.create_error(f"Frame {frame_index} not found")
            self._frame_states[frame_index] = frame_state

        capture_kwargs = {
            "force_full": force_full,
            "cursor_interactive": cursor_interactive,
            "selector": selector,
            "scope": scope,
            "compact": compact,
            "max_depth": max_depth,
            "max_tokens": max_tokens,
        }
        if include_bbox:
            capture_kwargs["include_bbox"] = True

        return await self._frame_states[frame_index].capture(**capture_kwargs)

    async def _create_frame_state(self, frame_index: int) -> FrameState | None:
        """Create Frame State管理器(lazy loading)

        Args:
            frame_index: Frame Index

        Returns:
            FrameState Instance,If Frame  not Exists则Return None
        """
        try:
            if frame_index == 0:
                frame = self._page
            else:
                if frame_index >= len(self._page.frames):
                    logger.warning(f"Frame {frame_index} out of range (total: {len(self._page.frames)})")
                    return None
                frame = self._page.frames[frame_index]

            state = FrameState(frame)
            logger.info(f"Created FrameState for frame {frame_index}")
            return state

        except Exception as exc:
            logger.warning(f"Failed to create state for frame {frame_index}: {exc}")
            return None

    async def cleanup_stale_frames(self) -> None:
        """Clean up失效  Frame 管理器"""
        current_frame_count = len(self._page.frames)
        stale_indices = [idx for idx in self._frame_states if idx >= current_frame_count]

        for idx in stale_indices:
            state = self._frame_states.pop(idx)
            await state.cleanup()
            logger.info(f"Cleaned up stale frame {idx}")

    def reset(self) -> None:
        """ResetAll Frame State(导航后Call)"""
        for state in self._frame_states.values():
            state.reset()
        self._frame_states.clear()
        logger.info("Reset all frame states")

    @property
    def stats(self) -> dict[str, object]:
        """GetStatisticsinformation"""
        return {
            "total_frames": len(self._frame_states),
            "frame_stats": {idx: state.stats for idx, state in self._frame_states.items()},
        }
