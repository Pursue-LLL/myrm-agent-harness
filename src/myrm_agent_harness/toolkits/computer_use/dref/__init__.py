"""@dref element reference package for semantic desktop control.

[INPUT]
- dref.types (POS: ElementRef, BBox, SnapshotMeta, SnapshotScope)
- dref.registry (POS: DRefRegistry session-scoped ref map)
- dref.errors (POS: DRefStaleError, AXPermissionRequiredError, AXTreeEmptyError)

[OUTPUT]
- Public @dref types, registry, and errors for computer_use consumers.

[POS]
Internal submodule of computer_use — not a standalone toolkit.
"""

from myrm_agent_harness.toolkits.computer_use.dref.errors import (
    AXPermissionRequiredError,
    AXTreeEmptyError,
    DRefStaleError,
    ElementRefError,
)
from myrm_agent_harness.toolkits.computer_use.dref.registry import DRefRegistry
from myrm_agent_harness.toolkits.computer_use.dref.types import (
    INTERACTIVE_AX_ROLES,
    BBox,
    ElementRef,
    SnapshotMeta,
    SnapshotScope,
)

__all__ = [
    "AXPermissionRequiredError",
    "AXTreeEmptyError",
    "BBox",
    "DRefRegistry",
    "DRefStaleError",
    "ElementRef",
    "ElementRefError",
    "INTERACTIVE_AX_ROLES",
    "SnapshotMeta",
    "SnapshotScope",
]
