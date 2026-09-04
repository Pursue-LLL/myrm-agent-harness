"""ARIA tree enhancer (Layer 3).

Adds metadata to AriaNode tree: ref IDs, semantic positions, scope filtering, nth deduplication.
Pure function design with no side effects.


[INPUT]

[OUTPUT]
- EnhancedNode tree with ref IDs and positions (immutable)
- refs: dict[str, RefInfo] mapping for Locator reconstruction

[POS]
Layer 3 of the four-layer ARIA snapshot architecture.
Adds ref IDs, semantic positions, scope filtering, and nth deduplication.
Role classification: 14 interactive + 21 content + 17 structural (52 total).
Single-pass nth handling with pre-counting for optimal performance.
Performance-optimized with O(1) dict-based role lookup.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import cast

from .aria_types import (
    AriaNode,
    BBox,
    BBoxData,
    BBoxMap,
    BBoxMapKey,
    EnhancedNode,
    RefInfo,
    calculate_semantic_position,
)

logger = logging.getLogger(__name__)

# Role category mapping for O(1) classification
_ROLE_CATEGORY: dict[str, str] = {
    # Interactive roles (14)
    "button": "interactive",
    "checkbox": "interactive",
    "combobox": "interactive",
    "link": "interactive",
    "listbox": "interactive",
    "menuitem": "interactive",
    "menuitemcheckbox": "interactive",
    "menuitemradio": "interactive",
    "option": "interactive",
    "radio": "interactive",
    "searchbox": "interactive",
    "slider": "interactive",
    "spinbutton": "interactive",
    "switch": "interactive",
    "tab": "interactive",
    "textbox": "interactive",
    "treeitem": "interactive",
    # Content roles (22)
    "heading": "content",
    "article": "content",
    "section": "content",
    "region": "content",
    "main": "content",
    "navigation": "content",
    "banner": "content",
    "contentinfo": "content",
    "complementary": "content",
    "cell": "content",
    "gridcell": "content",
    "columnheader": "content",
    "rowheader": "content",
    "listitem": "content",
    "img": "content",
    "figure": "content",
    "term": "content",
    "definition": "content",
    "blockquote": "content",
    "code": "content",
    "note": "content",
    # Structural roles (17)
    "generic": "structural",
    "group": "structural",
    "list": "structural",
    "table": "structural",
    "row": "structural",
    "rowgroup": "structural",
    "grid": "structural",
    "treegrid": "structural",
    "menu": "structural",
    "menubar": "structural",
    "toolbar": "structural",
    "tablist": "structural",
    "tree": "structural",
    "directory": "structural",
    "document": "structural",
    "application": "structural",
    "presentation": "structural",
    "none": "structural",
}

# Structural roles frozenset for compact mode filtering
_STRUCTURAL_ROLES = frozenset(
    {
        "generic",
        "group",
        "list",
        "table",
        "row",
        "rowgroup",
        "grid",
        "treegrid",
        "menu",
        "menubar",
        "toolbar",
        "tablist",
        "tree",
        "directory",
        "document",
        "application",
        "presentation",
        "none",
    }
)


def _role_in_scope(role: str, scope: str) -> bool:
    """Check if role should get a ref ID for the given scope.

    Optimized with single-lookup dict classification (O(1) instead of O(2)).
    """
    category = _ROLE_CATEGORY.get(role, "structural")

    if scope == "full":
        return True
    if scope == "interactive":
        return category == "interactive"
    if scope == "content-only":
        return category == "content"
    if scope == "content":
        return category in ("interactive", "content")
    return category == "interactive"


def _count_role_names(nodes: list[AriaNode], scope: str, filter_unnamed_structural: bool) -> Counter[BBoxMapKey]:
    """Pre-count all (role, name) pairs in the tree to determine uniqueness.

    This single pass enables single-traversal nth assignment without post-processing.

    Args:
        nodes: AriaNode tree to scan.
        scope: "interactive" | "content-only" | "content" | "full".
        filter_unnamed_structural: Skip unnamed structural elements in full mode.

    Returns:
        Counter mapping (role, name) tuples to occurrence counts.
    """
    counts: Counter[BBoxMapKey] = Counter()

    def _scan_node(node: AriaNode) -> None:
        role = node.role
        name = node.name

        should_assign_ref = _role_in_scope(role, scope)

        if should_assign_ref and scope == "full" and filter_unnamed_structural:
            is_unnamed_structural = not name and role in _STRUCTURAL_ROLES
            if is_unnamed_structural:
                should_assign_ref = False

        if should_assign_ref:
            counts[(role, name)] += 1

        for child in node.children:
            _scan_node(child)

    for node in nodes:
        _scan_node(node)

    return counts


def enhance_aria_tree(
    nodes: list[AriaNode],
    *,
    scope: str = "interactive",
    compact: bool = False,
    bbox_map: dict[str, dict[str, int | dict[str, int]]] | None = None,
    blocking_modal: dict[str, object] | None = None,
    hover_surfaces: list[dict[str, object]] | None = None,
) -> tuple[list[EnhancedNode], dict[str, RefInfo]]:
    """Enhance AriaNode tree with ref IDs, semantic positions, and scope filtering.

    Single-pass enhancement with pre-counting for optimal performance (O(2n)).

    Args:
        nodes: AriaNode tree from aria_parser.
        scope: Scope filter for ref assignment:
            - "interactive": Only interactive elements (buttons, links, inputs)
            - "content-only": Only content elements (headings, cells, articles)
            - "content": Interactive + content elements (default for most use cases)
            - "full": All elements including structural
        compact: Skip unnamed structural elements in full mode (token optimization).
        bbox_map: Optional bbox data keyed by "role:name" (string from JS).
        blocking_modal: Optional metadata of top-level blocking modal/backdrop layer.
        hover_surfaces: Optional list of detected hover surface triggers and sub-items.

    Returns:
        (enhanced_tree, refs) where:
        - enhanced_tree: Immutable EnhancedNode tree with ref IDs and positions
        - refs: dict[str, RefInfo] for Locator reconstruction

    Notes:
        - Phase 1: Pre-count all (role, name) pairs to determine uniqueness
        - Phase 2: Single-pass enhancement with correct nth assignment
        - No post-processing or object mutation required
        - Converts bbox_map string keys to tuple keys for type safety
    """
    # Convert bbox_map from JS string keys to type-safe tuple keys
    typed_bbox_map: BBoxMap | None = None
    if bbox_map:
        typed_bbox_map = {cast(BBoxMapKey, tuple(k.split(":", 1))): cast(BBoxData, v) for k, v in bbox_map.items()}

    # Map hover surface triggers: triggerName -> formatted hover_hint
    hover_map: dict[str, str] = {}
    if hover_surfaces:
        for surf in hover_surfaces:
            t_name = str(surf.get("triggerName", "")).strip()
            items = surf.get("subItems", [])
            if t_name and isinstance(items, list) and items:
                formatted_items = " | ".join(str(it) for it in items[:5])
                hover_map[t_name] = f"[hover first: {formatted_items}]"

    # Identify allowed inner interactive names if modal blocker is active
    modal_active = False
    allowed_inner_names: set[str] = set()
    if blocking_modal and isinstance(blocking_modal, dict):
        inner_names = blocking_modal.get("innerInteractive", [])
        if isinstance(inner_names, list) and inner_names:
            modal_active = True
            allowed_inner_names = {str(n).strip() for n in inner_names if str(n).strip()}

    # Phase 1: Pre-count (role, name) occurrences
    filter_unnamed_structural = compact
    role_name_totals = _count_role_names(nodes, scope, filter_unnamed_structural)

    # Phase 2: Single-pass enhancement
    refs: dict[str, RefInfo] = {}
    ref_counter = [0]
    role_name_nth_counters: Counter[BBoxMapKey] = Counter()

    def _enhance_node(node: AriaNode) -> EnhancedNode:
        """Recursively enhance a single node with correct nth from pre-counting."""
        role = node.role
        name = node.name

        # Blocking layer check: if modal is active and this element is outside
        is_blocked = False
        if modal_active and role in _ROLE_CATEGORY and _ROLE_CATEGORY[role] == "interactive":
            if name and name not in allowed_inner_names:
                is_blocked = True

        should_assign_ref = _role_in_scope(role, scope)

        # full+filter mode: skip unnamed structural elements
        is_unnamed_structural = not name and role in _STRUCTURAL_ROLES
        if should_assign_ref and scope == "full" and filter_unnamed_structural and is_unnamed_structural:
            should_assign_ref = False

        # If element is blocked by modal layer, do not assign ref ID to prevent LLM click interception
        if is_blocked:
            should_assign_ref = False

        ref_id = None
        bbox_data = None
        position = None
        nth_value = None

        if should_assign_ref:
            key: BBoxMapKey = (role, name)

            # Determine nth based on pre-counting
            total_count = role_name_totals[key]
            if total_count == 1:
                # Unique element: nth = None
                nth_value = None
            else:
                # Non-unique: assign incremental nth
                nth_value = role_name_nth_counters[key]
                role_name_nth_counters[key] += 1

            # Assign ref ID
            ref_id = f"e{ref_counter[0]}"
            ref_counter[0] += 1

            # Process bbox and semantic position
            if typed_bbox_map and key in typed_bbox_map:
                raw_bbox = typed_bbox_map[key]
                vp = raw_bbox["viewport"]

                # Handle viewport data with fallback to defaults
                if isinstance(vp, dict):
                    vp_width = vp.get("width", 1920)
                    vp_height = vp.get("height", 1080)
                else:
                    vp_width, vp_height = 1920, 1080

                bbox_data = BBox(
                    x=raw_bbox["x"],
                    y=raw_bbox["y"],
                    width=raw_bbox["width"],
                    height=raw_bbox["height"],
                    centerX=raw_bbox["centerX"],
                    centerY=raw_bbox["centerY"],
                    viewport_x=raw_bbox.get("viewportX", 0),
                    viewport_y=raw_bbox.get("viewportY", 0),
                    viewport_width=vp_width,
                    viewport_height=vp_height,
                )
                position = calculate_semantic_position(bbox_data)

            # Store RefInfo
            refs[ref_id] = RefInfo(role=role, name=name, nth=nth_value, bbox=bbox_data, position=position)

        # Hover surface hint lookup
        hover_hint = hover_map.get(name) if name else None

        # Recursively enhance children
        enhanced_children = tuple(_enhance_node(child) for child in node.children)

        return EnhancedNode(
            node=node,
            ref_id=ref_id,
            bbox=bbox_data,
            position=position,
            nth=nth_value,
            children=enhanced_children,
            hover_hint=hover_hint,
            is_blocked=is_blocked,
        )

    # Enhance all root nodes
    enhanced_nodes = [_enhance_node(node) for node in nodes]

    return enhanced_nodes, refs

