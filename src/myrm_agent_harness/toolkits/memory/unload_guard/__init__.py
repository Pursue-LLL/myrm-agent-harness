"""Public entry point for desktop/WebUI unload and graceful flush finalize guard.

Provides zero-LLM crash-proof emergency snapshotting and startup handoff recovery.
Strict typing applied: No `Any` types allowed.

[INPUT]
- toolkits.memory.unload_guard.guard::UnloadGracefulFlushGuard (POS: Atomic emergency graceful flush guard
  and session recovery manager.)
- toolkits.memory.unload_guard.snapshot_builder::ZeroLlmEmergencySnapshotBuilder (POS: Zero-LLM emergency
  snapshot generator for graceful unload and crash fallback.)
- toolkits.memory.unload_guard.types::EmergencyFlushRequest, EmergencyFlushResult, EmergencySnapshotReason,
  UnfinalizedSessionSummary (POS: Type definitions for desktop/WebUI unload and graceful flush finalize
  guard.)

[OUTPUT]
- Package facade re-exporting 6 public names: EmergencyFlushRequest, EmergencyFlushResult,
  EmergencySnapshotReason, UnfinalizedSessionSummary, UnloadGracefulFlushGuard,
  ZeroLlmEmergencySnapshotBuilder

[POS]
Public entry point for desktop/WebUI unload and graceful flush finalize guard.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.unload_guard.guard import UnloadGracefulFlushGuard
from myrm_agent_harness.toolkits.memory.unload_guard.snapshot_builder import (
    ZeroLlmEmergencySnapshotBuilder,
)
from myrm_agent_harness.toolkits.memory.unload_guard.types import (
    EmergencyFlushRequest,
    EmergencyFlushResult,
    EmergencySnapshotReason,
    UnfinalizedSessionSummary,
)

__all__ = [
    "EmergencyFlushRequest",
    "EmergencyFlushResult",
    "EmergencySnapshotReason",
    "UnfinalizedSessionSummary",
    "UnloadGracefulFlushGuard",
    "ZeroLlmEmergencySnapshotBuilder",
]
