"""Single-frame snapshot with MutationObserver-based change detection and caching.


[INPUT]
- patchright.async_api::Page (POS: Patchright page instance)
- patchright.async_api::Frame (POS: Patchright frame instance)
- snapshot.parser::parse_and_enhance_aria_tree (POS: ARIA tree parser)
- snapshot.parser::RefInfo (POS: element ref metadata)
- snapshot.observer_scripts::MUTATION_OBSERVER_SCRIPT (POS: DOM listener script)
- snapshot.observer_scripts::CURSOR_DETECT_SCRIPT (POS: cursor-interactive detection script)

[OUTPUT]
- AriaSnapshot: immutable snapshot result (dataclass) [re-exported from snapshot_types]
- SnapshotSource: snapshot source enum [re-exported from snapshot_types]
- SnapshotMetrics: snapshot metrics [re-exported from snapshot_types]
- FrameState: single-frame snapshot manager

[POS]
Single-frame snapshot manager. Responsibilities:
1. Manages MutationObserver for a single frame
2. Maintains ARIA tree cache
3. Detects cursor-interactive elements
4. Change detection strategy (0: CACHED, <5: FULL_WITH_CHANGES, >=5: FULL)
5. Cross-origin iframe fallback handling
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from ..exceptions import AriaAcquisitionError, AriaParseError
from .element_detectors import collect_bboxes, detect_cursor_interactive
from .observer_manager import ObserverManager
from .snapshot_types import AriaSnapshot, SnapshotMetrics, SnapshotSource

if TYPE_CHECKING:
    from patchright.async_api import Frame, Page

    from .aria_types import RefInfo

logger = logging.getLogger(__name__)


class FrameState:
    """Single-frame state manager.

    Provides MutationObserver change detection and cursor-interactive detection per frame:
    - Independent MutationObserver
    - Independent ARIA tree cache
    - Cursor-interactive detection (two stages: CSS selector + getComputedStyle)
    - Change detection strategy (0: CACHED, <5: FULL_WITH_CHANGES, >=5: FULL)
    - Cross-origin iframe degradation flow
    """

    def __init__(self, frame: Page | Frame):
        """Initialize the frame snapshot manager.

        Args:
            frame: Page or Frame instance.
        """
        self._frame = frame
        self._observer = ObserverManager(frame)
        self._cached_aria_tree: str | None = None
        self._cached_refs: dict[str, RefInfo] | None = None
        self._cached_cursor_elements: list[dict[str, str]] | None = None
        self._total_updates = 0
        self._incremental_updates = 0
        self._full_updates = 0
        self._bg_tasks: set[asyncio.Task[None]] = set()

    async def capture(
        self,
        force_full: bool = False,
        cursor_interactive: bool = False,
        selector: str = "",
        scope: str = "interactive",
        compact: bool = False,
        max_depth: int | None = None,
        include_bbox: bool = False,
        max_tokens: int = 0,
    ) -> AriaSnapshot:
        """Capture an ARIA snapshot (incremental or full).

        Args:
            force_full: Force a full update (after navigation or first call).
            cursor_interactive: Detect cursor:pointer and other interactive elements.
            selector: CSS selector (scopes the snapshot range).
            scope: Snapshot scope (interactive/content/full).
            compact: Compact format (saves ~30% tokens).
            max_depth: Optional depth limit (None = Fast Path, int = Custom Path with depth control).
            include_bbox: Whether to collect bbox data for semantic position (default False).
            max_tokens: Maximum token limit, 0 means unlimited.

        Returns:
            AriaSnapshot immutable snapshot result.
        """
        self._total_updates += 1

        if self._observer.is_cross_origin:
            return AriaSnapshot.create_cross_origin()

        if not self._observer.is_installed:
            await self._observer.install()

        if force_full or self._cached_aria_tree is None:
            return await self._full_update(
                cursor_interactive=cursor_interactive,
                selector=selector,
                scope=scope,
                compact=compact,
                max_depth=max_depth,
                include_bbox=include_bbox,
                max_tokens=max_tokens,
            )

        changes = await self._observer.get_changes()

        if not changes:
            # Never serve a poisoned empty cache (e.g. failed parse on about:blank before DOM updates).
            if self._cached_refs:
                return self._cached_snapshot(total_changes=0)
            return await self._full_update(
                cursor_interactive=cursor_interactive,
                selector=selector,
                scope=scope,
                compact=compact,
                max_depth=max_depth,
                include_bbox=include_bbox,
                max_tokens=max_tokens,
            )

        # Strategy selection: pick the update mode based on the change count
        total_changes = len(changes)
        self._incremental_updates += 1

        # Execute a full capture (updates the cache)
        snapshot = await self._full_update(
            cursor_interactive=cursor_interactive,
            selector=selector,
            scope=scope,
            compact=compact,
            max_depth=max_depth,
            include_bbox=include_bbox,
            max_tokens=max_tokens,
        )

        # Pick the source type based on the change count
        if total_changes < 5:
            return self._incremental_snapshot(snapshot, total_changes)
        else:
            return snapshot

    async def _full_update(
        self,
        *,
        cursor_interactive: bool = False,
        selector: str = "",
        scope: str = "interactive",
        compact: bool = False,
        max_depth: int | None = None,
        include_bbox: bool = False,
        max_tokens: int = 0,
    ) -> AriaSnapshot:
        """Perform a full update of the ARIA tree.

        Args:
            cursor_interactive: Whether to detect cursor:pointer elements.
            selector: CSS selector (scopes the snapshot range; empty string uses :root).
            scope: Snapshot scope (interactive/content/full).
            compact: Compact format (saves ~30% tokens).
            max_depth: Optional depth limit (None = Fast Path, int = Custom Path).
            include_bbox: Whether to collect bbox data (default False; adds ~20-30ms when enabled).
            max_tokens: Maximum token limit, 0 means unlimited.
        """
        from .aria_acquisition import get_aria_tree
        from .aria_enhancer import enhance_aria_tree
        from .aria_parser import parse_aria_yaml
        from .aria_renderer import render_to_yaml, smart_truncate_snapshot
        from .aria_types import RefInfo

        self._full_updates += 1

        locator_selector = selector or ":root"
        root_locator = self._frame.locator(locator_selector)

        # Enhance the DOM inside the specific frame before ARIA extraction
        try:
            await self._frame.evaluate("() => { if (window.__myrm_enhance_dom) window.__myrm_enhance_dom(); }")
        except Exception as exc:
            logger.debug(f"Failed to run dom enhancer on frame: {exc}")

        # Layer 1: ARIA Acquisition (Fast Path or Custom Path with maxDepth)
        try:
            aria_yaml = await get_aria_tree(root_locator, max_depth=max_depth)
        except Exception as exc:
            error = AriaAcquisitionError(
                f"Failed to acquire ARIA tree with selector '{locator_selector}'",
                context={"selector": selector, "locator": locator_selector},
                cause=exc,
            )
            logger.error(str(error))
            raise error from exc

        # Layer 2: Parse YAML to structured AriaNode tree
        try:
            aria_nodes = parse_aria_yaml(aria_yaml)
        except Exception as exc:
            error = AriaParseError(
                "Failed to parse ARIA YAML",
                context={"yaml_length": len(aria_yaml)},
                cause=exc,
            )
            logger.error(str(error))
            raise error from exc

        # Collect bbox data for semantic position enhancement (optional)
        bbox_map = {}
        if include_bbox:
            bbox_map = await collect_bboxes(self._frame, aria_yaml)

        # Layer 3: Enhance tree with ref IDs and semantic positions
        enhanced_nodes, refs = enhance_aria_tree(aria_nodes, scope=scope, compact=compact, bbox_map=bbox_map)

        # Layer 4: Render to text (with optional intelligent budget-aware truncation)
        was_truncated = False
        if max_tokens > 0:
            enhanced_tree, _meta, was_truncated = smart_truncate_snapshot(enhanced_nodes, max_tokens, compact=compact)
        else:
            enhanced_tree, _meta = render_to_yaml(enhanced_nodes, compact=compact)

        if was_truncated:
            try:
                from myrm_agent_harness.utils.event_utils import dispatch_custom_event

                warn_task = asyncio.create_task(
                    dispatch_custom_event(
                        "agent_status",
                        {
                            "step_key": "ux_warning_truncated",
                            "status": "warning",
                            "items": [
                                {
                                    "text": "Warning: The ARIA snapshot was intelligently truncated to fit within context limits."
                                }
                            ],
                            "metadata": {"type": "aria_truncation"},
                        },
                    )
                )
                self._bg_tasks.add(warn_task)
                warn_task.add_done_callback(self._bg_tasks.discard)
            except Exception as e:
                logger.warning(f"Failed to dispatch truncation event: {e}")

        if cursor_interactive:
            cursor_elements = await detect_cursor_interactive(self._frame)
            self._cached_cursor_elements = cursor_elements

            if cursor_elements:
                existing_names = {info.name for info in refs.values()}

                cursor_lines = []
                ref_counter = len(refs)

                for elem in cursor_elements:
                    name = elem["name"]
                    if name not in existing_names:
                        ref_id = f"e{ref_counter}"
                        refs[ref_id] = RefInfo(
                            role=elem["role"],
                            name=name,
                            nth=None,
                        )
                        cursor_lines.append(f'{ref_id}: {elem["role"]} "{name}"')
                        ref_counter += 1

                if cursor_lines:
                    enhanced_tree += "\n--- cursor-interactive ---\n" + "\n".join(cursor_lines)
        else:
            self._cached_cursor_elements = None

        self._cached_aria_tree = enhanced_tree
        self._cached_refs = refs

        logger.info(f"Full update completed ({len(refs)} refs)")

        return AriaSnapshot(
            tree=enhanced_tree,
            refs=refs,
            source=SnapshotSource.FULL,
            timestamp=time.time(),
            metrics=SnapshotMetrics(
                ref_count=len(refs),
                estimated_tokens=len(enhanced_tree) // 4,
                changed_regions=0,
                total_changes=0,
            ),
        )

    def _cached_snapshot(self, total_changes: int = 0) -> AriaSnapshot:
        """ReturnCacheSnapshot"""
        return AriaSnapshot(
            tree=self._cached_aria_tree or "",
            refs=self._cached_refs or {},
            source=SnapshotSource.CACHED,
            timestamp=time.time(),
            metrics=SnapshotMetrics(
                ref_count=len(self._cached_refs or {}),
                estimated_tokens=len(self._cached_aria_tree or "") // 4,
                changed_regions=0,
                total_changes=total_changes,
            ),
        )

    def _incremental_snapshot(self, base_snapshot: AriaSnapshot, total_changes: int) -> AriaSnapshot:
        """Create an incremental snapshot.

        Args:
            base_snapshot: Base snapshot.
            total_changes: Change count.

        Returns:
            A snapshot marked as FULL_WITH_CHANGES.
        """
        return AriaSnapshot(
            tree=base_snapshot.tree,
            refs=base_snapshot.refs,
            source=SnapshotSource.FULL_WITH_CHANGES,
            timestamp=base_snapshot.timestamp,
            metrics=(
                SnapshotMetrics(
                    ref_count=(base_snapshot.metrics.ref_count if base_snapshot.metrics else 0),
                    estimated_tokens=(base_snapshot.metrics.estimated_tokens if base_snapshot.metrics else 0),
                    changed_regions=total_changes,
                    total_changes=total_changes,
                )
                if base_snapshot.metrics
                else None
            ),
        )

    def reset(self) -> None:
        """Reset state (call after navigation)."""
        self._cached_aria_tree = None
        self._cached_refs = None
        self._cached_cursor_elements = None
        self._observer.reset()

    async def cleanup(self) -> None:
        """Clean up resources (call when the frame is deleted)."""
        await self._observer.disconnect()
        self.reset()

    @property
    def stats(self) -> dict[str, object]:
        """Frame snapshot statistics (update counts and cache hit rate)."""
        return {
            "total_updates": self._total_updates,
            "incremental_updates": self._incremental_updates,
            "full_updates": self._full_updates,
            "cache_hit_rate": (self._incremental_updates / self._total_updates if self._total_updates > 0 else 0),
            "has_cache": self._cached_aria_tree is not None,
            "is_cross_origin": self._observer.is_cross_origin,
        }
