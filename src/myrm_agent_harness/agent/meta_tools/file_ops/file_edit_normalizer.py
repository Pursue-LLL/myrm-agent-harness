"""Normalize heterogeneous LLM file_edit_tool payloads into edits[].

[INPUT]
- (none — pure dict parsing)

[OUTPUT]
- normalize_edits_payload: Coerce flat or JSON-string edits into edits[]
- merge_edits_for_diff: Combined old/new strings for UI diff preview

[POS]
LLM input normalizer for file_edit_tool. Accepts legacy flat old_str/new_str without exposing them in schema.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any


def _coerce_edit_item(raw: Any) -> dict[str, str]:
    if isinstance(raw, Mapping):
        old = raw.get("old_str")
        if old is None:
            old = raw.get("old_string")
        new = raw.get("new_str")
        if new is None:
            new = raw.get("new_string")
        if old is None:
            raise ValueError("Each edit requires old_str")
        return {"old_str": str(old), "new_str": "" if new is None else str(new)}
    raise ValueError("Each edit must be an object with old_str and new_str")


def normalize_edits_payload(data: Mapping[str, Any]) -> list[dict[str, str]]:
    """Return normalized edits list from raw tool args (supports legacy flat fields)."""
    if "edits" in data and data["edits"] is not None:
        edits_raw = data["edits"]
        if isinstance(edits_raw, str):
            parsed = json.loads(edits_raw)
            if not isinstance(parsed, list):
                raise ValueError("edits JSON string must decode to an array")
            edits_raw = parsed
        if not isinstance(edits_raw, Sequence) or isinstance(edits_raw, (str, bytes)):
            raise ValueError("edits must be an array")
        return [_coerce_edit_item(item) for item in edits_raw]

    old = data.get("old_str")
    if old is None:
        old = data.get("old_string")
    if old is None:
        raise ValueError("file_edit_tool requires edits[] or old_str/new_str")

    new = data.get("new_str")
    if new is None:
        new = data.get("new_string")
    return [{"old_str": str(old), "new_str": "" if new is None else str(new)}]


def merge_edits_for_diff(edits: Sequence[Mapping[str, str]]) -> tuple[str, str]:
    """Build combined old/new strings for UI diff preview."""
    if not edits:
        return "", ""
    if len(edits) == 1:
        item = edits[0]
        return str(item.get("old_str", "")), str(item.get("new_str", ""))
    old_parts: list[str] = []
    new_parts: list[str] = []
    for index, item in enumerate(edits, start=1):
        old_parts.append(f"--- edit {index} ---\n{item.get('old_str', '')}")
        new_parts.append(f"--- edit {index} ---\n{item.get('new_str', '')}")
    return "\n".join(old_parts), "\n".join(new_parts)


__all__ = ["merge_edits_for_diff", "normalize_edits_payload"]
