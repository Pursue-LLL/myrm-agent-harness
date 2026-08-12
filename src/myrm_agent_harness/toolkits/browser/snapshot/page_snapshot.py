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
    """Multi-frame registry manager.

    Coordinates multiple FrameState instances, providing a unified multi-frame
    snapshot interface:
    - Lazy loading: FrameState is created only on first access.
    - Invalidity detection: auto-cleans up already-deleted frames.
    - Lifecycle management: auto-resets after navigation.
    - iframe refs prefix: f1_e0, f2_e1 format.
    - Cursor-interactive detection: propagated to all frames.
    - Snapshot source aggregation: if any frame did a full update, the whole result is full.
    """

    def __init__(self, page: Page):
        """Initialize the multi-frame registry manager.

        Args:
            page: Patchright Page instance.
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
        """Capture a complete page snapshot (main frame + iframes).

        Args:
            include_iframes: Whether to include iframe content.
            force_full: Force a full update.
            cursor_interactive: Detect cursor:pointer and other interactive elements.
            selector: CSS selector (scopes the snapshot range).
            max_depth: Optional depth limit (None = Fast Path, int = Custom Path).
            scope: Snapshot scope (interactive/content/full).
            compact: Compact format (saves ~30% tokens).
            include_bbox: Collect bbox data (auto-enabled in debug mode).
            max_tokens: Maximum token limit, 0 means unlimited.

        Returns:
            (aria_tree, refs, source) tuple; refs in iframes use the f{i}_{ref_id} key format.
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
        """Get the snapshot for a specified frame (lazy loading).

        Args:
            frame_index: Frame index (0 = main frame, 1+ = iframes).
            force_full: Force a full update.
            cursor_interactive: Detect cursor:pointer elements.
            selector: CSS selector (scopes the snapshot range).
            scope: Snapshot scope (interactive/content/full).
            compact: Compact format (saves ~30% tokens).
            max_depth: Optional depth limit (None = Fast Path, int = Custom Path).
            include_bbox: Collect bbox data (auto-enabled in debug mode).
            max_tokens: Maximum token limit, 0 means unlimited.

        Returns:
            AriaSnapshot snapshot result.
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
        """Create a frame state manager (lazy loading).

        Args:
            frame_index: Frame index.

        Returns:
            FrameState instance, or None if the frame does not exist.
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
        """Clean up stale frame managers."""
        current_frame_count = len(self._page.frames)
        stale_indices = [idx for idx in self._frame_states if idx >= current_frame_count]

        for idx in stale_indices:
            state = self._frame_states.pop(idx)
            await state.cleanup()
            logger.info(f"Cleaned up stale frame {idx}")

    def reset(self) -> None:
        """Reset all frame states (call after navigation)."""
        for state in self._frame_states.values():
            state.reset()
        self._frame_states.clear()
        logger.info("Reset all frame states")

    @property
    def stats(self) -> dict[str, object]:
        """Get statistics information."""
        return {
            "total_frames": len(self._frame_states),
            "frame_stats": {idx: state.stats for idx, state in self._frame_states.items()},
        }
