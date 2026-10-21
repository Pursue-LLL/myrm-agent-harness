"""[INPUT]
- .models: CapabilityHintChip, CommandCategory, CommandMatrixEntry, ContextStateSnapshot
- .engine: CapabilityDiscoveryEngine

[OUTPUT]
- Facade exports for context-aware capability discovery and command matrix

[POS]
Harness framework layer facade for Item 38 P0.
"""

from .engine import CapabilityDiscoveryEngine
from .models import (
    CapabilityHintChip,
    CommandCategory,
    CommandMatrixEntry,
    ContextStateSnapshot,
)

__all__ = [
    "CapabilityDiscoveryEngine",
    "CapabilityHintChip",
    "CommandCategory",
    "CommandMatrixEntry",
    "ContextStateSnapshot",
]
