"""Category mapping and argument parsing shared by the memory agent tools.

[INPUT]
- toolkits.memory.types::MemoryType (POS: memory type enum)

[OUTPUT]
- CATEGORY_TO_TYPE: agent-visible category name -> MemoryType
- parse_string_list: normalise a list / JSON array / comma-separated string argument

[POS]
Stateless helpers for memory_search/save/manage tool arguments.
"""

from __future__ import annotations

import json

from myrm_agent_harness.toolkits.memory.types import MemoryType

CATEGORY_TO_TYPE: dict[str, MemoryType] = {
    "knowledge": MemoryType.SEMANTIC,
    "claim": MemoryType.CLAIM,
    "event": MemoryType.EPISODIC,
    "pitfall": MemoryType.EPISODIC,
    "preference": MemoryType.PROFILE,
    "rule": MemoryType.PROCEDURAL,
    "instruction": MemoryType.PROCEDURAL,
    "integration": MemoryType.INTEGRATION,
}


def parse_string_list(val: list[str] | str | None) -> list[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    try:
        parsed = json.loads(val)
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
    except (json.JSONDecodeError, TypeError):
        pass
    return [t.strip() for t in val.split(",") if t.strip()]
