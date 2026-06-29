"""@dref element reference types and session registry for desktop semantic control."""

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
