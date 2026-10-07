"""Session lifecycle log archive and offline bundle export types.

Defines schemas for execution logs, token billing snapshots, artifact entries,
sanitization policies, and offline export bundles.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- ToolExecutionStatus: Execution status for a tool call entry.
- ToolExecutionLogEntry: Detailed log record of a single tool invocation.
- TokenCostBillingSnapshot: Token consumption and cost accounting snapshot.
- ArtifactSnapshotEntry: Snapshot of a generated workspace or session artifact.
- SessionExecutionTurn: Structured record of one full interaction turn.
- SanitizationPolicy: Configuration for sensitive credentials and private data masking.
- SessionLogArchiveBundle: Immutable self-contained bundle for offline migration and audit.
- ImportReplayResult: Result of importing and verifying an archived session bundle.

[POS]
Session lifecycle log archive and offline bundle export types.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class ToolExecutionStatus(StrEnum):
    """Execution status for a tool call entry."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class ToolExecutionLogEntry:
    """Detailed log record of a single tool invocation."""

    call_id: str
    tool_name: str
    arguments: dict[str, str]
    result_payload: str
    duration_ms: float
    status: ToolExecutionStatus
    timestamp: str
    error_message: str | None = None


@dataclass(frozen=True)
class TokenCostBillingSnapshot:
    """Token consumption and cost accounting snapshot."""

    prompt_tokens: int
    completion_tokens: int
    cache_hit_tokens: int
    estimated_cost_usd: float

    @property
    def total_tokens(self) -> int:
        """Calculate total consumed tokens."""
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class ArtifactSnapshotEntry:
    """Snapshot of a generated workspace or session artifact."""

    artifact_id: str
    name: str
    mime_type: str
    content_text: str
    version_hash: str
    created_at: str


@dataclass(frozen=True)
class SessionExecutionTurn:
    """Structured record of one full interaction turn."""

    turn_id: int
    user_input: str
    assistant_response: str
    tool_calls: list[ToolExecutionLogEntry] = field(default_factory=list)
    token_billing: TokenCostBillingSnapshot = field(
        default_factory=lambda: TokenCostBillingSnapshot(0, 0, 0, 0.0)
    )
    errors: list[str] = field(default_factory=list)
    timestamp: str = ""


@dataclass(frozen=True)
class SanitizationPolicy:
    """Configuration for sensitive credentials and private data masking."""

    mask_api_keys: bool = True
    mask_private_ips: bool = True
    mask_user_home_paths: bool = True
    mask_emails: bool = True
    custom_patterns: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SessionLogArchiveBundle:
    """Immutable self-contained bundle for offline migration and audit."""

    session_id: str
    workspace_name: str
    created_at: str
    exported_at: str
    turns: list[SessionExecutionTurn]
    artifacts: list[ArtifactSnapshotEntry]
    total_billing: TokenCostBillingSnapshot
    is_sanitized: bool
    checksum_sha256: str


@dataclass(frozen=True)
class ImportReplayResult:
    """Result of importing and verifying an archived session bundle."""

    session_id: str
    success: bool
    verified_checksum: bool
    turn_count: int
    artifact_count: int
    total_tokens: int
    message: str
