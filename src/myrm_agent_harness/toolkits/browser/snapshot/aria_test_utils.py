"""Testing utilities for parsing rendered ARIA tree strings.


[INPUT]

[OUTPUT]
- extract_ref_ids: Extract ref IDs from rendered aria_tree
- parse_ref_line: Parse individual ref line

[POS]
Testing utilities for parsing rendered ARIA tree strings.
NOT part of core parsing logic (Layer 2), but a helper for unit/E2E tests.
"""

from __future__ import annotations

import re

_REF_ID_PATTERN = re.compile(r"\[ref=((f\d+_)?e\d+)\]")
_ROLE_PATTERN = re.compile(r"-\s+(\w+)")
_NAME_PATTERN = re.compile(r'"([^"]*)"')


def extract_ref_ids(aria_tree: str, name_filter: str = "", role_filter: str = "") -> list[str]:
    """Extract ref_ids from rendered aria_tree string.

    Args:
        aria_tree: Rendered ARIA tree string with ref IDs (e.g., '- button "Submit" [ref=e0]')
        name_filter: Optional filter for element name (substring match)
        role_filter: Optional filter for element role (substring match)

    Returns:
        List of ref_ids (e.g., ['e0', 'e1', 'f1_e0'])
    """
    lines = aria_tree.split("\n")
    ref_ids = []

    for line in lines:
        match = _REF_ID_PATTERN.search(line)
        if not match:
            continue

        if name_filter and name_filter not in line:
            continue
        if role_filter and role_filter not in line:
            continue

        ref_ids.append(match.group(1))

    return ref_ids


def parse_ref_line(line: str) -> tuple[str, str, str] | None:
    """Parse a single rendered aria_tree line with ref.

    Args:
        line: Single line from rendered aria_tree (e.g., '  - button "Submit" [ref=e0]')

    Returns:
        Tuple of (ref_id, role, name) or None if line has no ref
    """
    ref_match = _REF_ID_PATTERN.search(line)
    if not ref_match:
        return None

    ref_id = ref_match.group(1)

    role_match = _ROLE_PATTERN.search(line)
    role = role_match.group(1) if role_match else ""

    name_match = _NAME_PATTERN.search(line)
    name = name_match.group(1) if name_match else ""

    return ref_id, role, name
