"""Element detection utilities for snapshot enhancement.

[INPUT]
- (none)

[OUTPUT]
- detect_cursor_interactive: detect cursor:pointer etc.caninteractionelement
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
    """detect cursor:pointer etc.caninteractionelement

    Args:
        frame: Page or Frame instance

    Returns:
        elementlist,format:[{name, role}]
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
