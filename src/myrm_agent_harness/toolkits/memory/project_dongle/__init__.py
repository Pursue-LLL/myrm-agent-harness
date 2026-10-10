"""Project Context USB Dongle and cross-agent relay package.

[INPUT]
- Re-exports core domain types, parsers, spill managers, and coordinator.

[OUTPUT]
- Public package interface for Item 152 ProjectContextUsbDongleAndCrossAgentRelaySuite.

[POS]
- Package root facade in toolkits/memory/project_dongle.
"""

from __future__ import annotations

from .archive_spill import ArchiveSpillManager
from .block_parser import parse_blocks, render_file
from .dongle_manager import ProjectContextDongleManager
from .models import (
    DongleArchivePointer,
    DongleBlock,
    DongleBlockType,
    DongleState,
    SyncResult,
)

__all__ = [
    "ArchiveSpillManager",
    "DongleArchivePointer",
    "DongleBlock",
    "DongleBlockType",
    "DongleState",
    "ProjectContextDongleManager",
    "SyncResult",
    "parse_blocks",
    "render_file",
]
