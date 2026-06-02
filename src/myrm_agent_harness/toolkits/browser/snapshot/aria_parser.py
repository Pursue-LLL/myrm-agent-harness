"""ARIA tree YAML parser (Layer 2).

Converts YAML string (from Playwright ariaSnapshot API) into structured AriaNode tree.
Uses pyyaml standard library for robust parsing (supports escape chars, multiline, Unicode).


[INPUT]

[OUTPUT]
- AriaNode tree: Structured representation of accessibility tree

[POS]
Layer 2 of the four-layer ARIA snapshot architecture.
Converts text to structured data using pyyaml standard library.
"""

from __future__ import annotations

import logging
from typing import Any

from .aria_types import AriaNode

logger = logging.getLogger(__name__)


def parse_aria_yaml(aria_tree: str) -> list[AriaNode]:
    """Parse YAML-formatted ARIA tree into structured AriaNode objects.

    Args:
        aria_tree: YAML string from Playwright aria_snapshot() or custom traverser.

    Returns:
        List of root AriaNode objects (typically one WebArea root).

    Raises:
        yaml.YAMLError: If YAML parsing fails.

    Notes:
        - Uses pyyaml.safe_load for security and correctness
        - Supports all YAML features: escape chars, multiline strings, Unicode
        - Empty input returns empty list
    """
    if not aria_tree or not aria_tree.strip():
        return []

    import yaml

    try:
        data = yaml.safe_load(aria_tree)
    except yaml.YAMLError as exc:
        logger.error(f"Failed to parse ARIA YAML: {exc}")
        raise

    if not data:
        return []

    # YAML data is a list of dicts, each representing an element
    # Format: [{role: {name: ..., children: [...]}}]
    return _parse_yaml_nodes(data, indent=0)


def _parse_yaml_nodes(data: list[Any] | dict[str, Any] | str | None, indent: int = 0) -> list[AriaNode]:
    """Recursively parse YAML data structure into AriaNode tree.

    YAML structure variants:
    1. List of dicts: [{ "button": {...} }, { "link": {...} }]
    2. Dict with children: { "WebArea": { "children": [...] } }
    3. Simple string: "button name" (role and name concatenated)
    """
    if not data:
        return []

    # Case 1: List of elements
    if isinstance(data, list):
        nodes = []
        for item in data:
            nodes.extend(_parse_yaml_nodes(item, indent))
        return nodes

    # Case 2: Dict with role as key
    if isinstance(data, dict):
        nodes = []
        for role, value in data.items():
            # Extract name and children
            if isinstance(value, dict):
                name = value.get("name", "")
                attributes = {k: str(v) for k, v in value.items() if k not in ("name", "children")}
                children_data = value.get("children", [])
                children = _parse_yaml_nodes(children_data, indent + 1)
            elif isinstance(value, list):
                # Handle case where value is directly a list of children
                name = ""
                attributes = {}
                children = _parse_yaml_nodes(value, indent + 1)
            elif isinstance(value, str):
                name = value
                attributes = {}
                children = []
            elif value is None:
                name = ""
                attributes = {}
                children = []
            else:
                logger.warning(f"Unexpected value type for role {role}: {type(value)}")
                continue

            node = AriaNode(role=role, name=name, attributes=attributes, children=children, indent=indent)
            nodes.append(node)
        return nodes

    # Case 3: String format (e.g., 'button "Click Me"', "heading 'Title' [level=1]")
    if isinstance(data, str):
        # Try to parse string format: "role 'name' [attributes]" or 'role "name" [attributes]'
        # Support both single and double quotes
        import re

        # Pattern: role followed by quoted name and optional attributes
        pattern = r'^(\w+)\s+["\']([^"\']*)["\'](?:\s+(.+))?$'
        match = re.match(pattern, data.strip())

        if match:
            role = match.group(1)
            name = match.group(2)
            attributes_str = match.group(3) or ""

            # Parse attributes like [level=1]
            attributes = {}
            if attributes_str.strip().startswith("[") and attributes_str.strip().endswith("]"):
                attr_content = attributes_str.strip()[1:-1]
                for attr_pair in attr_content.split(","):
                    if "=" in attr_pair:
                        key, value = attr_pair.split("=", 1)
                        attributes[key.strip()] = value.strip()

            node = AriaNode(role=role, name=name, attributes=attributes, children=[], indent=indent)
            return [node]

        # Fallback: treat entire string as role with empty name
        logger.warning(f"Unexpected string format in YAML data: {data}")
        return []

    logger.warning(f"Unexpected data type: {type(data)}")
    return []
