"""XML UI hierarchy parser and @mref reference generator for Android uiautomator.

[INPUT]
- types::MobileUIElement (POS: element data model)

[OUTPUT]
- MobileUIParser: Parses XML string into structured @mref index map and element trees.

[POS]
High-performance XML parser for Android uiautomator dump, generating compact @mref semantic trees.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET

from myrm_agent_harness.toolkits.mobile_adb.types import MobileUIElement

logger = logging.getLogger(__name__)

BOUNDS_REGEX = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


class MobileUIParser:
    """Parses Android uiautomator XML dump into structured MobileUIElements."""

    @classmethod
    def parse_bounds(cls, bounds_str: str) -> tuple[int, int, int, int]:
        """Extract (left, top, right, bottom) from '[left,top][right,bottom]'."""
        match = BOUNDS_REGEX.match(bounds_str)
        if not match:
            return 0, 0, 0, 0
        left, top, right, bottom = map(int, match.groups())
        return left, top, right, bottom

    @classmethod
    def parse_xml_tree(
        cls, xml_content: str, max_elements: int = 100
    ) -> tuple[list[MobileUIElement], dict[str, MobileUIElement]]:
        """Parse raw uiautomator XML into elements and ref_id lookup map.

        Args:
            xml_content: The raw XML output from 'uiautomator dump'.
            max_elements: Upper bound of elements to prevent context explosion.

        Returns:
            A tuple of (ordered_elements_list, ref_id_to_element_dict).
        """
        if not xml_content or not xml_content.strip():
            return [], {}

        elements: list[MobileUIElement] = []
        ref_map: dict[str, MobileUIElement] = {}
        counter = 1

        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            logger.warning("MobileUIParser failed to parse XML: %s", e)
            return [], {}

        for node in root.iter("node"):
            text = node.attrib.get("text", "").strip()
            content_desc = node.attrib.get("content-desc", "").strip()
            resource_id = node.attrib.get("resource-id", "").strip()
            class_name = node.attrib.get("class", "").strip()
            bounds_str = node.attrib.get("bounds", "")
            clickable = node.attrib.get("clickable", "false") == "true"
            scrollable = node.attrib.get("scrollable", "false") == "true"
            editable = (
                node.attrib.get("focusable", "false") == "true"
                and "EditText" in class_name
            )
            enabled = node.attrib.get("enabled", "true") == "true"
            focused = node.attrib.get("focused", "false") == "true"
            package_name = node.attrib.get("package", "").strip()

            # Filter out invisible or meaningless structural containers with no text/desc/clickable
            if not clickable and not scrollable and not editable and not text and not content_desc:
                continue

            bounds = cls.parse_bounds(bounds_str)
            # Filter zero-size or off-screen elements
            if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
                continue

            ref_id = f"@mref_{counter}"
            element = MobileUIElement(
                ref_id=ref_id,
                class_name=class_name,
                resource_id=resource_id,
                text=text,
                content_desc=content_desc,
                bounds=bounds,
                clickable=clickable,
                scrollable=scrollable,
                editable=editable,
                enabled=enabled,
                focused=focused,
                package_name=package_name,
            )
            elements.append(element)
            ref_map[ref_id] = element
            counter += 1

            if len(elements) >= max_elements:
                break

        return elements, ref_map
