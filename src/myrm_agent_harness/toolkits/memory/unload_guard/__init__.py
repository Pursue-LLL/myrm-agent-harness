# [POS]: myrm_agent_harness/toolkits/memory/unload_guard/__init__.py
# [INPUT]: None
# [OUTPUT]: UnloadGracefulFlushGuard, ZeroLlmEmergencySnapshotBuilder, Types
"""Public entry point for desktop/WebUI unload and graceful flush finalize guard.

Provides zero-LLM crash-proof emergency snapshotting and startup handoff recovery.
Strict typing applied: No `Any` types allowed.
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
