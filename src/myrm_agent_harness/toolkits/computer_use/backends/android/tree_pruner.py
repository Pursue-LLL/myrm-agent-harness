"""Accessibility UIAutomator XML Tree Pruner & Semantic Markdown Formatter.

[INPUT]
- xml_content: str (Android UIAutomator dump XML)

[OUTPUT]
- MobileNode: Structured interactive element representation
- AndroidUiPruner: Parses and prunes 90%+ container noise into compact LLM-friendly Markdown

[POS]
Token optimization and semantic parsing engine for mobile computer use.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import NamedTuple

logger = logging.getLogger(__name__)


class MobileNode(NamedTuple):
    index: int
    text: str
    content_desc: str
    resource_id: str
    class_name: str
    clickable: bool
    editable: bool
    bounds: tuple[int, int, int, int]  # (x1, y1, x2, y2)
    center: tuple[int, int]  # (cx, cy)


class AndroidUiPruner:
    """Parses Android UIAutomator XML and prunes non-interactive layout containers."""

    BOUNDS_PATTERN = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")

    @classmethod
    def parse_bounds(cls, bounds_str: str) -> tuple[int, int, int, int]:
        """Parse bounds string '[x1,y1][x2,y2]' into tuple (x1, y1, x2, y2)."""
        match = cls.BOUNDS_PATTERN.match(bounds_str)
        if match:
            return (
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
                int(match.group(4)),
            )
        return (0, 0, 0, 0)

    @classmethod
    def extract_interactive_nodes(cls, xml_str: str) -> list[MobileNode]:
        """Extract interactive and text-bearing leaf/actionable elements from XML."""
        if not xml_str or not xml_str.strip():
            return []

        try:
            root = ET.fromstring(xml_str)
        except ET.ParseError as exc:
            logger.warning("Failed to parse Android UI XML: %s", exc)
            return []

        nodes: list[MobileNode] = []
        idx = 1

        for elem in root.iter("node"):
            text = (elem.attrib.get("text") or "").strip()
            content_desc = (elem.attrib.get("content-desc") or "").strip()
            resource_id = (elem.attrib.get("resource-id") or "").strip()
            class_name = elem.attrib.get("class", "").split(".")[-1]
            clickable = elem.attrib.get("clickable", "false").lower() == "true"
            editable = (
                elem.attrib.get("focusable", "false").lower() == "true"
                and "edittext" in class_name.lower()
            ) or elem.attrib.get("editable", "false").lower() == "true"
            bounds_raw = elem.attrib.get("bounds", "[0,0][0,0]")
            x1, y1, x2, y2 = cls.parse_bounds(bounds_raw)

            # Skip 0-area invisible components
            if x2 <= x1 or y2 <= y1:
                continue

            # Keep only actionable or meaningful text elements
            is_actionable = clickable or editable or "button" in class_name.lower()
            has_semantic_content = bool(text or content_desc)

            if is_actionable or has_semantic_content:
                cx = (x1 + x2) // 2
                cy = (y1 + y2) // 2
                node = MobileNode(
                    index=idx,
                    text=text,
                    content_desc=content_desc,
                    resource_id=resource_id.split("/")[-1] if "/" in resource_id else resource_id,
                    class_name=class_name,
                    clickable=clickable,
                    editable=editable,
                    bounds=(x1, y1, x2, y2),
                    center=(cx, cy),
                )
                nodes.append(node)
                idx += 1

        return nodes

    @classmethod
    def to_markdown_summary(cls, nodes: list[MobileNode]) -> str:
        """Format extracted nodes into a compact, low-token Markdown outline."""
        if not nodes:
            return "No visible interactive elements detected on current screen."

        lines = ["### 📱 Current Screen Interactive Elements:"]
        for node in nodes:
            label_parts: list[str] = []
            if node.text:
                label_parts.append(f'text="{node.text}"')
            if node.content_desc and node.content_desc != node.text:
                label_parts.append(f'desc="{node.content_desc}"')
            if node.resource_id:
                label_parts.append(f'id="{node.resource_id}"')

            label = " | ".join(label_parts) if label_parts else node.class_name
            attrs: list[str] = []
            if node.clickable:
                attrs.append("clickable")
            if node.editable:
                attrs.append("editable (input)")

            attr_str = f" [{', '.join(attrs)}]" if attrs else ""
            lines.append(
                f"- **[@m{node.index}]** {node.class_name}{attr_str} | {label} -> Center({node.center[0]}, {node.center[1]})"
            )

        return "\n".join(lines)
