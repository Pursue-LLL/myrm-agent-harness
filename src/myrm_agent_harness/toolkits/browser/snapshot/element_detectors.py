"""Element detection utilities for snapshot enhancement.

[INPUT]
- (none)

[OUTPUT]
- detect_cursor_interactive: Detect cursor:pointer etc. interactive elements
- collect_bboxes: Collect bounding boxes for all elements in ARIA tree (Lay...

[POS]
Element detection utilities for snapshot enhancement.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from patchright.async_api import Frame, Page

logger = logging.getLogger(__name__)


async def detect_cursor_interactive(frame: Page | Frame) -> list[dict[str, str]]:
    """Detect elements that show a cursor:pointer (interactive) style.

    Args:
        frame: Page or Frame instance

    Returns:
        Element list, format: [{name, role}]
    """
    from .observer_scripts import CURSOR_DETECT_SCRIPT

    try:
        elements = await asyncio.wait_for(
            frame.evaluate(CURSOR_DETECT_SCRIPT),
            timeout=3.0,
        )
        if isinstance(elements, list):
            logger.info(f"Detected {len(elements)} cursor-interactive elements")
            return elements
        return []
    except Exception as exc:
        logger.warning(f"Failed to detect cursor-interactive elements: {exc}")
        return []


async def collect_bboxes(frame: Page | Frame, aria_tree: str) -> dict[str, dict[str, int | dict[str, int]]]:
    """Collect bounding boxes for all elements in ARIA tree (Layer 1).

    Args:
        frame: Page or Frame instance
        aria_tree: Raw ARIA tree YAML string

    Returns:
        Dict keyed by "role:name" with bbox coordinates
    """
    from .aria_parser import parse_aria_yaml
    from .observer_scripts import BBOX_COLLECTOR_SCRIPT

    try:
        nodes = parse_aria_yaml(aria_tree)
    except Exception as exc:
        logger.warning(f"Failed to parse ARIA tree for bbox collection: {exc}")
        return {}

    role_name_pairs = []

    def _extract_pairs(node_list: list) -> None:
        """Recursively extract (role, name) pairs from AriaNode tree."""
        for node in node_list:
            if node.name:
                role_name_pairs.append({"role": node.role, "name": node.name})
            if node.children:
                _extract_pairs(node.children)

    _extract_pairs(nodes)

    if not role_name_pairs:
        return {}

    try:
        bbox_map = await asyncio.wait_for(
            frame.evaluate(BBOX_COLLECTOR_SCRIPT, role_name_pairs),
            timeout=3.0,
        )
        if isinstance(bbox_map, dict):
            logger.info(f"Collected bboxes for {len(bbox_map)} elements")
            return bbox_map
        return {}
    except Exception as exc:
        logger.warning(f"Failed to collect bboxes: {exc}")
        return {}


async def detect_blocking_modal(frame: Page | Frame) -> dict[str, object] | None:
    """Detect top-level blocking modal dialog or backdrop layer.

    Args:
        frame: Page or Frame instance

    Returns:
        Dict with modal metadata (role, coverage, zIndex, innerInteractive) or None
    """
    from .observer_scripts import MODAL_BLOCKING_SCRIPT

    try:
        modal_info = await asyncio.wait_for(
            frame.evaluate(MODAL_BLOCKING_SCRIPT),
            timeout=2.0,
        )
        if isinstance(modal_info, dict):
            logger.info(
                "Detected blocking layer: role=%s, coverage=%s, zIndex=%s",
                modal_info.get("role"),
                modal_info.get("coverage"),
                modal_info.get("zIndex"),
            )
            return modal_info
        return None
    except Exception as exc:
        logger.debug("Blocking modal detection non-critical failure: %s", exc)
        return None


async def detect_hover_surfaces(frame: Page | Frame) -> list[dict[str, object]]:
    """Detect interactive trigger elements that reveal hover surfaces.

    Args:
        frame: Page or Frame instance

    Returns:
        List of dicts: [{triggerName, triggerRole, subItems: [...]}]
    """
    from .observer_scripts import HOVER_SURFACE_SCRIPT

    try:
        surfaces = await asyncio.wait_for(
            frame.evaluate(HOVER_SURFACE_SCRIPT),
            timeout=2.0,
        )
        if isinstance(surfaces, list):
            logger.info("Detected %d hover surfaces", len(surfaces))
            return surfaces
        return []
    except Exception as exc:
        logger.debug("Hover surfaces detection non-critical failure: %s", exc)
        return []

