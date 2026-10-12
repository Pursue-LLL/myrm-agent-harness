"""Category mapping, argument parsing and resolver type shared by the memory MCP tools.

[INPUT]
- toolkits.memory.types::MemoryType (POS: memory type enum)
- toolkits.memory.manager::MemoryManager (POS: memory lifecycle manager, TYPE_CHECKING only)

[OUTPUT]
- CATEGORY_TO_TYPE: MCP-visible category name -> MemoryType
- parse_string_list: normalise a list / JSON array / comma-separated string argument
- ManagerResolver: zero-argument callable returning the MemoryManager of the current request

[POS]
Stateless helpers for the recall/list/store/manage tool handlers.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory.types import MemoryType

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager

type ManagerResolver = Callable[[], MemoryManager]

CATEGORY_TO_TYPE: dict[str, MemoryType] = {
    "knowledge": MemoryType.SEMANTIC,
    "claim": MemoryType.CLAIM,
    "event": MemoryType.EPISODIC,
    "preference": MemoryType.PROFILE,
    "rule": MemoryType.PROCEDURAL,
    "instruction": MemoryType.PROCEDURAL,
}


def parse_string_list(val: str | list[str] | None) -> list[str]:
    """Parse a comma-separated string / JSON array / raw list into non-empty items.

    Accepts the three shapes an LLM may produce when calling an MCP tool:
    a literal list, a JSON-encoded array, or a comma-separated string.
    """
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x).strip() for x in val if x is not None and str(x).strip()]
    try:
        parsed = json.loads(val)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if x is not None and str(x).strip()]
    except (json.JSONDecodeError, TypeError):
        pass
    return [part.strip() for part in val.split(",") if part.strip()]
