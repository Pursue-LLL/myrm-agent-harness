"""IPC Message Clamping and Large Artifact Spillover Suite (Item 216).

[INPUT]
- ipc_clamping_types: Strongly typed contracts and configurations.
- ipc_clamping_engine: IpcMessageClampingAndSpilloverEngine implementation.

[OUTPUT]
- Public exports of IPC Message Clamping and Spillover Suite.

[POS]
- Provides physical clamping floors and automated artifact offloading for oversized
- inter-agent communications, safeguarding multi-agent context stability.
"""

from .ipc_clamping_engine import IpcMessageClampingAndSpilloverEngine
from .ipc_clamping_types import (
    IpcClampingAction,
    IpcClampingConfig,
    IpcClampingOutcome,
    SpilloverArtifactSpec,
)

__all__ = [
    "IpcClampingAction",
    "IpcClampingConfig",
    "IpcClampingOutcome",
    "IpcMessageClampingAndSpilloverEngine",
    "SpilloverArtifactSpec",
]
