"""Data models for Content Hash Approval Binding and JIT Dual Verification.

[POS]
Immutable fingerprints capturing physical asset state at approval request time,
and structured verification results for Just-In-Time execution-instant assertions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class AssetType(StrEnum):
    """Classification of an asset bound to an approval decision."""

    FILE = "file"
    COMMAND = "command"
    STRUCTURED_ACTION = "structured_action"


@dataclass(frozen=True, slots=True)
class AssetContentFingerprint:
    """Immutable cryptographic fingerprint of a physical asset bound to an approval."""

    asset_type: AssetType
    asset_identifier: str  # File path or action descriptor
    content_sha256: str
    st_size: int | None = None
    st_mtime_ns: int | None = None
    captured_at: float = field(default_factory=time.time)
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Convert fingerprint to serializable dictionary for approval payload storage."""
        return {
            "asset_type": self.asset_type.value,
            "asset_identifier": self.asset_identifier,
            "content_sha256": self.content_sha256,
            "st_size": self.st_size,
            "st_mtime_ns": self.st_mtime_ns,
            "captured_at": self.captured_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> AssetContentFingerprint:
        """Construct fingerprint from serialized approval payload dictionary."""
        return cls(
            asset_type=AssetType(str(data.get("asset_type", AssetType.FILE.value))),
            asset_identifier=str(data.get("asset_identifier", "")),
            content_sha256=str(data.get("content_sha256", "")),
            st_size=int(data["st_size"]) if data.get("st_size") is not None else None,
            st_mtime_ns=int(data["st_mtime_ns"]) if data.get("st_mtime_ns") is not None else None,
            captured_at=float(data.get("captured_at", time.time())),
            metadata={str(k): str(v) for k, v in dict(data.get("metadata", {})).items()},
        )


@dataclass(frozen=True, slots=True)
class JITVerificationResult:
    """Result of Just-In-Time execution instant dual assertion."""

    is_valid: bool
    failure_reason: str | None = None
    current_sha256: str | None = None
    expected_sha256: str | None = None
    details: dict[str, object] = field(default_factory=dict)
