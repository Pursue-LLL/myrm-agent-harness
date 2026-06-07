"""MemoryManager public entry.

[INPUT]
- memory._manager (POS: composed MemoryManager implementation)

[OUTPUT]
- MemoryManager, MemoryError, MemoryNotFoundError, MemoryTaintedError
- _infer_preference_category (internal helper re-export for tests)

[POS]
Stable public import path for the memory toolkit façade.
"""

from myrm_agent_harness.toolkits.memory._manager import (
    MemoryError,
    MemoryManager,
    MemoryNotFoundError,
    MemoryTaintedError,
)
from myrm_agent_harness.toolkits.memory._manager.helpers import _infer_preference_category

__all__ = [
    "MemoryError",
    "MemoryManager",
    "MemoryNotFoundError",
    "MemoryTaintedError",
    "_infer_preference_category",
]
