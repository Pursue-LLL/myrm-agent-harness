"""Data models for Snapshot Lag Aware Memory Freshness and Disk Verification Contract.

[INPUT]
- Session ID, initial memory snapshot strings, disk write events, and turn indices.

[OUTPUT]
- MemorySnapshotDigest, SessionWriteDelta, SnapshotFreshnessState, DirectDiskReadHint, and DeltaPatchBlock.

[POS]
- Harness framework middleware layer for memory snapshot freshness and intra-session delta patching.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

WriteActionType = Literal["create", "update", "delete"]


class MemorySnapshotDigest(BaseModel):
    """Cryptographic or monotonic digest tracking the version of injected memory context."""

    digest: str
    session_id: str
    created_at: str
    initial_items_count: int = 0


class SessionWriteDelta(BaseModel):
    """Incremental fact mutated or committed during an ongoing multi-turn session."""

    key: str
    content: str
    turn_index: int = 0
    written_at: str = ""
    action: WriteActionType = "update"


class SnapshotFreshnessState(BaseModel):
    """Current staleness and dirty state of memory snapshot for an active session."""

    session_id: str
    snapshot_digest: str
    is_dirty: bool = False
    deltas: list[SessionWriteDelta] = Field(default_factory=list)
    latest_disk_version: int = 1


class DirectDiskReadHint(BaseModel):
    """Contract hint prompting the agent to directly inspect persistent disk storage."""

    session_id: str
    hint_message: str
    affected_keys: list[str] = Field(default_factory=list)
    is_dirty: bool = False


class DeltaPatchBlock(BaseModel):
    """Formatted incremental delta block appendable to system instructions without busting prompt cache."""

    header: str
    patches: list[str] = Field(default_factory=list)
    formatted_block: str = ""
