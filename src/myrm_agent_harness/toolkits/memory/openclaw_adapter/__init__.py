"""Public facade of the openclaw adapter subsystem.

[INPUT]
- toolkits.memory.openclaw_adapter.crash_rescuer::OpenClawCrashRescuer (POS: Crash recovery engine for
  corrupted OpenClaw SQLite databases.)
- toolkits.memory.openclaw_adapter.types::OpenClawMemoryEntryV2, OpenClawParsedBundle, OpenClawSessionNode,
  OpenClawVersion, RescueReport (POS: Typed data contracts for the openclaw adapter subsystem.)
- toolkits.memory.openclaw_adapter.v2_parser::OpenClawV2Parser (POS: Parser and format adapter for OpenClaw
  2.0 multi-user, Swarm topology, and structured memories.)

[OUTPUT]
- Package facade re-exporting 7 public names: OpenClawCrashRescuer, OpenClawMemoryEntryV2,
  OpenClawParsedBundle, OpenClawSessionNode, OpenClawV2Parser, OpenClawVersion, RescueReport

[POS]
Public facade of the openclaw adapter subsystem.
"""

from .crash_rescuer import OpenClawCrashRescuer
from .types import (
    OpenClawMemoryEntryV2,
    OpenClawParsedBundle,
    OpenClawSessionNode,
    OpenClawVersion,
    RescueReport,
)
from .v2_parser import OpenClawV2Parser

__all__ = [
    "OpenClawCrashRescuer",
    "OpenClawMemoryEntryV2",
    "OpenClawParsedBundle",
    "OpenClawSessionNode",
    "OpenClawV2Parser",
    "OpenClawVersion",
    "RescueReport",
]
