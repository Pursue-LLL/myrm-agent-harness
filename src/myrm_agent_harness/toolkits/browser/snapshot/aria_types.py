"""Type definitions for ARIA snapshot architecture.

Four-layer architecture types:
- Layer 1 (Acquisition): Returns YAML string
- Layer 2 (Parser): Produces AriaNode tree
- Layer 3 (Enhancer): Produces EnhancedNode tree + refs
- Layer 4 (Renderer): Produces final text output


[OUTPUT]
- BBox: Element边界框坐标(viewport-relative)
- RefInfo: Element ref 元Data(role/name/nth/bbox/position)
- SnapshotMeta: Snapshot元information(ref_count + token 估算)
- AriaNode: ARIA 树节点(Layer 2 output)
- EnhancedNode: 带 ref ID  and 语义Position 节点(Layer 3 output)
- ViewportData: viewport 尺寸 exactType定义
- BBoxData: bbox Data exactType定义
- BBoxMapKey: bbox_map  TypeSecurity key (role, name) tuple
- BBoxMap: complete bbox_map  Type定义
- calculate_semantic_position: BBox 配套Tool，Compute语义PositionDescription
- resolve_locator:  from  RefInfo 重建 Playwright Locator
- CURSOR_ROLES: cursor-interactive Element 虚拟 role 集合

[POS]
Core data types and utility functions for the ARIA Snapshot architecture.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple, TypedDict

if TYPE_CHECKING:
    from patchright.async_api import Frame, Locator, Page


class ViewportData(TypedDict):
    """Viewport dimensions from JavaScript getBoundingClientRect context."""

    width: int
    height: int


class BBoxData(TypedDict):
    """Raw bounding box data from JavaScript, with viewport context."""

    x: int
    y: int
    width: int
    height: int
    centerX: int
    centerY: int
    viewportX: int
    viewportY: int
    viewport: ViewportData


BBoxMapKey = tuple[str, str]
BBoxMap = dict[BBoxMapKey, BBoxData]


class BBox(NamedTuple):
    """Element bounding box coordinates (viewport-relative)"""

    x: int
    y: int
    width: int
    height: int
    centerX: int  # noqa: N815  match JS getBoundingClientRect API
    centerY: int  # noqa: N815  match JS getBoundingClientRect API
    viewport_x: int
    viewport_y: int
    viewport_width: int
    viewport_height: int


class RefInfo(NamedTuple):
    """Metadata needed to reconstruct a Playwright Locator from a ref ID.

    ``nth`` is ``None`` for unique ``(role, name)`` pairs — the Locator
    needs no ``.nth()`` disambiguation.  Non-None values are 0-based indices
    among elements sharing the same ``(role, name)``.

    ``bbox`` and ``position`` are optional spatial metadata for semantic location enhancement.
    """

    role: str
    name: str
    nth: int | None
    bbox: BBox | None = None
    position: str | None = None


class SnapshotMeta(NamedTuple):
    """Quantitative metadata about a snapshot, enabling informed optimization decisions."""

    ref_count: int
    estimated_tokens: int


class AriaNode:
    """Structured representation of an ARIA tree node (Layer 2 output).

    Produced by aria_parser from YAML string. Contains role, name, and hierarchy
    information. Enhanced by Layer 3 to add ref IDs and semantic positions.
    """

    __slots__ = ("attributes", "children", "indent", "name", "role")

    def __init__(
        self,
        role: str,
        name: str = "",
        attributes: dict[str, str] | None = None,
        children: list[AriaNode] | None = None,
        indent: int = 0,
    ):
        self.role = role
        self.name = name
        self.attributes = attributes or {}
        self.children = children or []
        self.indent = indent

    def __repr__(self) -> str:
        return f"AriaNode(role={self.role!r}, name={self.name!r}, children={len(self.children)})"


@dataclass(frozen=True, slots=True)
class EnhancedNode:
    """Enhanced ARIA node with ref IDs and semantic positions (Layer 3 output).

    Produced by aria_enhancer. Contains all metadata needed for rendering
    and Locator reconstruction.

    Immutable by design (frozen=True) to ensure functional purity.
    """

    node: AriaNode
    ref_id: str | None = None
    bbox: BBox | None = None
    position: str | None = None
    nth: int | None = None
    children: tuple[EnhancedNode, ...] = ()

    def __repr__(self) -> str:
        return f"EnhancedNode(role={self.node.role!r}, ref_id={self.ref_id!r}, children={len(self.children)})"


CURSOR_ROLES = frozenset({"clickable", "focusable"})


def calculate_semantic_position(bbox: BBox) -> str:
    """Calculate semantic position descriptor from bounding box (配套ToolFunction).

    Maps absolute coordinates to human-readable position like "at top-left".
    Uses 3x3 grid division: top/center/bottom x left/center/right.

    Args:
        bbox: BBox instance with centerX/centerY and viewport dimensions.

    Returns:
        Position string like "at top-left", "at center", "at right".
    """
    vw = bbox.viewport_width
    vh = bbox.viewport_height

    vertical = "top" if bbox.centerY < vh * 0.33 else "bottom" if bbox.centerY > vh * 0.67 else "center"
    horizontal = "left" if bbox.centerX < vw * 0.33 else "right" if bbox.centerX > vw * 0.67 else "center"

    if vertical == "center" and horizontal == "center":
        return "at center"
    if vertical == "center":
        return f"at {horizontal}"
    if horizontal == "center":
        return f"at {vertical}"
    return f"at {vertical}-{horizontal}"


def resolve_locator(page_or_frame: Page | Frame, info: RefInfo) -> Locator:
    """Reconstruct a Playwright Locator from ref metadata.

    Cursor-interactive elements (role in ``CURSOR_ROLES``) are located via
    ``get_by_text`` since they lack proper ARIA roles. All other elements
    use the standard ``get_by_role`` path.

    When ``info.nth`` is ``None`` (unique element), no ``.nth()`` call is
    made — the Locator is simpler and more resilient to DOM reordering.

    Args:
        page_or_frame: Patchright Page or Frame instance.
        info: RefInfo metadata containing role, name, and nth.

    Returns:
        Playwright Locator for the element.
    """
    if info.role in CURSOR_ROLES:
        loc = page_or_frame.get_by_text(info.name, exact=True)
    else:
        loc = page_or_frame.get_by_role(info.role, name=info.name)
    return loc.nth(info.nth) if info.nth is not None else loc
