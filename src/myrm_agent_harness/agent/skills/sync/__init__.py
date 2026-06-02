"""Skill Sync — cross-device / cross-sandbox skill synchronization.

Provides Protocol-driven bidirectional skill sync for three deployment modes:
- Local/Tauri: file-system-based multi-device sync (iCloud/Dropbox/NAS)
- SaaS: HTTP-based sync via control-plane shared repository
- Community: opt-in skill sharing marketplace

[OUTPUT]
- SkillSyncProtocol: Protocol for skill sync backends
- SkillQualityGateProtocol: Protocol for push quality gate
- SkillSyncManager: Sync orchestrator
- SkillSyncManifest: Persistent sync state
- LocalFSSyncBackend: File-system-based sync backend
- ThresholdQualityGate: Default quality gate

[POS]
Skill synchronization module — collective skill evolution enabler.
"""

from .local_sync import LocalFSSyncBackend
from .manager import SkillSyncManager
from .manifest import SkillSyncManifest
from .protocols import SkillQualityGateProtocol, SkillSyncProtocol
from .quality_gate import ThresholdQualityGate
from .types import (
    ConflictStrategy,
    GateVerdict,
    PullResult,
    PushResult,
    RemoteSkillEntry,
    SyncDirection,
    SyncStatus,
)

__all__ = [
    "ConflictStrategy",
    "GateVerdict",
    "LocalFSSyncBackend",
    "PullResult",
    "PushResult",
    "RemoteSkillEntry",
    "SkillQualityGateProtocol",
    "SkillSyncManager",
    "SkillSyncManifest",
    "SkillSyncProtocol",
    "SyncDirection",
    "SyncStatus",
    "ThresholdQualityGate",
]
