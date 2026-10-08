"""Type definitions for Four-Zone Workspace Layout and Read-Only Source Protection.

[INPUT]
None.

[OUTPUT]
- WorkspaceZone: Enum for standard 4-zone workspace topology
- ZoneOperationType: Read, write, delete, rename, promote
- ZoneValidationResult: Check outcome
- ReadOnlySourceZoneViolationError: Exception raised on mutating operations in 01_原始材料
- ZonePromotionRecord: Telemetry record for one-way promotions across zones

[POS]
Harness core security contracts for workspace isolation, preventing overwrite
of customer original assets and enforcing one-way artifact promotion.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class WorkspaceZone(StrEnum):
    """Authoritative four-zone workspace layout categories."""

    ZONE_01_RAW = "01_原始材料"
    ZONE_02_DRAFT = "02_过程草稿"
    ZONE_03_CANONICAL = "03_内容底稿"
    ZONE_04_DELIVERABLE = "04_交付成果"


class ZoneOperationType(StrEnum):
    """File operation categories evaluated against zone policies."""

    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    RENAME = "rename"
    PROMOTE = "promote"


@dataclass(frozen=True, slots=True)
class ZoneValidationResult:
    """Result of validating an operation against zone invariant policies."""

    allowed: bool
    zone: WorkspaceZone | None
    reason: str


@dataclass(frozen=True, slots=True)
class ZonePromotionRecord:
    """Audit record capturing single-direction artifact promotion."""

    promotion_id: str
    source_zone: WorkspaceZone
    target_zone: WorkspaceZone
    source_path: str
    target_path: str
    promoted_by: str
    promoted_at: float = field(default_factory=time.time)


class ReadOnlySourceZoneViolationError(Exception):
    """Raised when an agent attempts a mutating operation on protected Zone 01 original assets."""

    def __init__(self, file_path: str, operation: str) -> None:
        message = (
            f"FORBIDDEN: '{WorkspaceZone.ZONE_01_RAW.value}' is strictly READ-ONLY to protect "
            f"customer original assets. Attempted '{operation}' on '{file_path}'. "
            f"Please copy to '{WorkspaceZone.ZONE_02_DRAFT.value}' before modifying."
        )
        super().__init__(message)
        self.file_path = file_path
        self.operation = operation
