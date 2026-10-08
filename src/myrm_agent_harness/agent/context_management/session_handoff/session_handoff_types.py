"""Types for session handoff package, readonly share grant, secret gate, and line blame."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class ShareAccessStatus(str, Enum):
    """Status of a readonly share grant access attempt."""

    GRANTED = "granted"
    EXPIRED = "expired"
    QUOTA_EXCEEDED = "quota_exceeded"
    PASSWORD_REQUIRED = "password_required"
    INVALID_PASSWORD = "invalid_password"
    REVOKED = "revoked"


class SecretSeverity(str, Enum):
    """Severity tier for identified secret leakage."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class HandoffMessageTurn:
    """Individual conversational turn within a packaged handoff."""

    turn_id: int
    role: str
    content: str
    tool_calls_summary: Optional[str] = None
    artifacts_generated: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class SessionHandoffPackage:
    """Self-contained portable session bundle ready for sharing or handoff restoration."""

    package_id: str
    session_id: str
    creator_id: str
    topic_summary: str
    created_at_iso: str
    manifest_hash: str
    turns: List[HandoffMessageTurn] = field(default_factory=list)
    environment_variables_exported: Dict[str, str] = field(default_factory=dict)
    workspace_snapshot_hash: str = "workspace-clean"


@dataclass(frozen=True)
class ReadonlyShareGrant:
    """Cryptographic grant for browser/remote viewer of a session package."""

    grant_id: str
    package_id: str
    share_url_token: str
    created_at_iso: str
    expires_at_iso: str
    max_views: int
    current_views: int
    password_hash: Optional[str] = None
    is_revoked: bool = False


@dataclass(frozen=True)
class SecretFinding:
    """Detected secret pattern occurrence."""

    rule_name: str
    severity: SecretSeverity
    pattern_matched: str
    location_hint: str
    masked_placeholder: str


@dataclass(frozen=True)
class SecretGateScanResult:
    """Outcome of pre-publish dual-tier secret gate verification."""

    passed: bool
    findings_count: int
    critical_findings_count: int
    findings: List[SecretFinding] = field(default_factory=list)
    rejection_reason: Optional[str] = None


@dataclass(frozen=True)
class LineBlameEntry:
    """Line-level mapping linking code line range to generating session turn."""

    file_path: str
    start_line: int
    end_line: int
    session_id: str
    turn_id: int
    prompt_intent_digest: str
    timestamp_iso: str


@dataclass(frozen=True)
class LineBlameLookupResult:
    """Result when inspecting source code line provenance."""

    file_path: str
    line_number: int
    found: bool
    entry: Optional[LineBlameEntry] = None
