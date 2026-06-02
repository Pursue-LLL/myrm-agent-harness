"""Snapshot module - ARIA tree parsing with MutationObserver-based change detection.


[INPUT]
- patchright.async_api::Page (POS: Patchright page instance)
- patchright.async_api::Frame (POS: Patchright frame instance)

[OUTPUT]
- BBox: element bounding box coordinates (viewport-relative)
- RefInfo: element ref metadata (includes bbox and position)
- SnapshotMeta: snapshot meta information
- resolve_locator: rebuild Playwright Locator from RefInfo
- calculate_semantic_position: BBox utility, computes semantic position description
- truncate_snapshot: truncate snapshot by token budget
- CURSOR_ROLES: virtual role set for cursor-interactive elements
- AriaSnapshot: immutable ARIA snapshot
- SnapshotSource: snapshot source type
- SnapshotMetrics: snapshot statistical metrics
- FrameState: single-frame state manager
- FrameRegistry: multi-frame registry manager
- extract_ref_ids: test utility, extracts ref IDs from rendered aria_tree
- parse_ref_line: test utility, parses a single ref info line

[POS]
Snapshot module. Provides comprehensive snapshot capabilities:
1. aria_types: core data types (AriaNode, EnhancedNode, BBox, RefInfo) + utilities (resolve_locator, calculate_semantic_position, CURSOR_ROLES) + precise type system (TypedDict)
2. aria_acquisition: ARIA tree retrieval (Fast/Custom dual path)
3. aria_parser: YAML parsing (pyyaml)
4. aria_enhancer: tree enhancement (ref + semantic position + scope) + role classification constants + single-pass nth handling
5. aria_renderer: text rendering (YAML/compact) + text post-processing (truncate_snapshot)
6. aria_test_utils: test utilities (extract_ref_ids, parse_ref_line)
7. observer_scripts: JS scripts (MutationObserver, cursor detection, BBox collection)
8. frame_snapshot: single-frame state management (with BBox collection)
9. page_snapshot: multi-frame registry management

Core capabilities: pure four-layer architecture + MutationObserver change detection + multi-frame aggregation + semantic position enhancement + immutable data structures
"""

from .aria_acquisition import get_aria_tree
from .aria_enhancer import enhance_aria_tree
from .aria_parser import parse_aria_yaml
from .aria_renderer import render_to_yaml, truncate_snapshot
from .aria_test_utils import extract_ref_ids, parse_ref_line
from .aria_types import (
    CURSOR_ROLES,
    AriaNode,
    BBox,
    EnhancedNode,
    RefInfo,
    SnapshotMeta,
    calculate_semantic_position,
    resolve_locator,
)
from .frame_snapshot import AriaSnapshot, FrameState, SnapshotMetrics, SnapshotSource
from .page_snapshot import FrameRegistry

__all__ = [
    "CURSOR_ROLES",
    "AriaNode",
    # Snapshot management
    "AriaSnapshot",
    # Type definitions and utilities
    "BBox",
    "EnhancedNode",
    "FrameRegistry",
    "FrameState",
    "RefInfo",
    "SnapshotMeta",
    "SnapshotMetrics",
    "SnapshotSource",
    "calculate_semantic_position",
    "enhance_aria_tree",
    # Rendered aria_tree parsing utilities
    "extract_ref_ids",
    # Four-layer architecture (A10)
    "get_aria_tree",
    "parse_aria_yaml",
    "parse_ref_line",
    "render_to_yaml",
    "resolve_locator",
    # Text post-processing
    "truncate_snapshot",
]
