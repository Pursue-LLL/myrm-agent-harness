"""Snapshot generation with ARIA tree capture and change detection.


[INPUT]
- patchright.async_api::Page (POS: Patchright page instance)
- snapshot::FrameRegistry (POS: multi-frame registry manager)
- snapshot::RefInfo (POS: element ref metadata)
- session.snapshot_diff::SnapshotDiffEngine (POS: semantic diff)
- session.snapshot_suggestion::generate_snapshot_suggestion (POS: large page suggestion)

[OUTPUT]
- SnapshotManager: snapshot generation manager
- SnapshotResult: defined in `snapshot_result.py`; this module's `__all__` also exports `SnapshotResult` and `_REF_PREFIX_RE`

[POS]
Snapshot generation manager. Responsibilities:
1. ARIA snapshot generation (delegates to FrameRegistry)
2. Diff baseline management (delegates to SnapshotDiffEngine)
3. Token-related parameters (compact/selector/max_tokens)
4. Parameter orchestration (passes cursor_interactive etc. to FrameRegistry)

Single responsibility: only handles snapshot business logic; does not handle navigation, interaction, extraction, etc.
Architecture: delegates to FrameRegistry for multi-frame MutationObserver change detection, cursor-interactive detection, and ref prefix handling.
Behavior: FrameRegistry may return cached results when DOM hasn't changed; cache hits depend on `SnapshotSource` and other runtime state.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.browser.snapshot import SnapshotMeta

from .snapshot_diff import _REF_PREFIX_RE, SnapshotDiffEngine
from .snapshot_result import SnapshotResult
from .snapshot_suggestion import generate_snapshot_suggestion

__all__ = ["_REF_PREFIX_RE", "SnapshotManager", "SnapshotResult"]

if TYPE_CHECKING:
    from patchright.async_api import Page

_ESTIMATED_CHARS_PER_TOKEN = 4


class SnapshotManager:
    """SnapshotGenerate管理器 — 单一职责

    职责:
    1. ARIA SnapshotGenerate(委托 FrameRegistry)
    2. Diff 基线维护(委托 SnapshotDiffEngine)
    3. compact/selector/max_tokens  etc.output形态控制
    4. Cursor-interactive 检测

     not 涉 and :导航、交互、Extract etc.业务逻辑。
    """

    def __init__(self, page: Page):
        """Initialize SnapshotManager

        Args:
            page: Patchright Page Instance
        """
        self._page = page
        self._diff = SnapshotDiffEngine()

        from myrm_agent_harness.toolkits.browser.snapshot import (
            FrameRegistry,
            SnapshotSource,
        )

        self._frame_registry = FrameRegistry(page)
        self._snapshot_source = SnapshotSource

    async def get_snapshot(
        self,
        scope: str = "content",
        compact: bool = False,
        selector: str = "",
        max_tokens: int = 0,
        diff: bool = True,
        cursor_interactive: bool = True,
        include_iframes: bool = True,
        max_depth: int | None = None,
        include_bbox: bool = False,
    ) -> SnapshotResult:
        """Generate ARIA Snapshot(含 iframe 穿透)

        Args:
            scope: SnapshotRange(interactive/content/full)
            compact: 紧凑Format(单行化output，usually短于Default YAML 形态)
            selector: CSS 选择器(限定Range,Set时Skip iframe)
            max_tokens: Token 预算(0= no 限)
            diff: 启用语义感知 diff
            cursor_interactive: 检测 cursor:pointer Element
            include_iframes: Contains iframe Content(Auto遍历All iframe)
            max_depth: Optional depth limit (None = Fast Path, int = Custom Path)
            include_bbox: 收集 bbox Data(Debug ModeAuto启用)

        Returns:
            SnapshotResult Contains ARIA 树 and  refs(iframe refs Format:f1_e0, f2_e1)
        """
        # 1. Generate suggestion (skip diff check here, done after return)
        aria_tree, refs, _source = await self._frame_registry.capture(
            include_iframes=include_iframes and not selector,
            force_full=False,
            cursor_interactive=cursor_interactive,
            selector=selector,
            scope=scope,
            compact=compact,
            max_depth=max_depth,
            include_bbox=include_bbox,
            max_tokens=max_tokens if not diff else 0,  # Only truncate the full tree if we aren't doing a semantic diff
        )

        meta = SnapshotMeta(
            ref_count=len(refs),
            estimated_tokens=len(aria_tree) // _ESTIMATED_CHARS_PER_TOKEN,
        )

        suggestion = generate_snapshot_suggestion(
            ref_count=meta.ref_count,
            estimated_tokens=meta.estimated_tokens,
            current_scope=scope,
            current_compact=compact,
            current_selector=selector,
        )

        original_tree = aria_tree
        is_diff_output = diff and self._diff.has_baseline()
        if is_diff_output:
            aria_tree = self._diff.generate_diff(original_tree, refs, max_tokens, _ESTIMATED_CHARS_PER_TOKEN)

        self._diff.update_baseline(original_tree, refs)

        if suggestion:
            aria_tree = f" Optimization tip: {suggestion}\n\n{aria_tree}"

        return SnapshotResult(
            aria_tree=aria_tree,
            refs=MappingProxyType(refs),
            meta=meta,
            is_incremental=is_diff_output,
        )

    def reset_diff_baseline(self) -> None:
        """Reset diff 基线（导航后Call）"""
        self._diff.reset()
        self._frame_registry.reset()

    def _generate_suggestion(
        self,
        ref_count: int,
        estimated_tokens: int,
        current_scope: str,
        current_compact: bool,
        current_selector: str,
    ) -> str:
        """Generate optimization suggestion for large snapshots.

        This is a convenience wrapper around generate_snapshot_suggestion function.
        """
        return generate_snapshot_suggestion(
            ref_count,
            estimated_tokens,
            current_scope,
            current_compact,
            current_selector,
        )

    @property
    def stats(self) -> dict[str, object]:
        """GetStatisticsinformation( for 监控)"""
        return {
            "has_baseline": self._diff.has_baseline(),
            "frame_registry": self._frame_registry.stats,
        }
