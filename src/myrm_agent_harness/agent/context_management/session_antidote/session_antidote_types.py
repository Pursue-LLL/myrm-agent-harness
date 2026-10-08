"""Types and schemas for session anti-poisoning and antidote suite.

Defines genesis config snapshots, mutation proposals, poison severity,
watchdog reports, and antidote receipts.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- PoisonSeverity: Severity classification for session configuration poisoning.
- FlagScope: Scope defining whether a configuration flag persists or is ephemeral.
- GenesisConfigSnapshot: Immutable snapshot of the baseline configuration for a session.
- ConfigMutationProposal: Proposal to mutate or inject configuration flags into a session.
- ConfigDriftDetail: Detailed observation of a detected configuration drift or injection.
- PoisonDiagnosisReport: Diagnostic report produced by the poison watchdog.
- AntidoteReceipt: Receipt generated upon successful execution of 1-Click Antidote.
- SessionAntidoteConfig: Runtime configuration for anti-poisoning engine and watchdog.

[POS]
Types and schemas for session anti-poisoning and antidote suite.
"""

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import time


class PoisonSeverity(str, Enum):
    """Severity classification for session configuration poisoning."""

    CLEAN = "clean"
    SUSPICIOUS = "suspicious"
    POTENTIALLY_POISONED = "potentially_poisoned"
    SEVERELY_POISONED = "severely_poisoned"


class FlagScope(str, Enum):
    """Scope defining whether a configuration flag persists or is ephemeral."""

    EPHEMERAL_TURN = "ephemeral_turn"
    PERSISTENT_APPROVED = "persistent_approved"
    REJECTED_BLOCKED = "rejected_blocked"


@dataclass(frozen=True)
class GenesisConfigSnapshot:
    """Immutable snapshot of the baseline configuration for a session."""

    session_id: str
    genesis_timestamp: float
    base_flags: dict[str, str]
    checksum: str

    @classmethod
    def create(cls, session_id: str, base_flags: dict[str, str]) -> "GenesisConfigSnapshot":
        """Compute SHA256 checksum and construct immutable snapshot."""
        serialized = json.dumps(base_flags, sort_keys=True)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return cls(
            session_id=session_id,
            genesis_timestamp=time.time(),
            base_flags=dict(base_flags),
            checksum=digest,
        )


@dataclass
class ConfigMutationProposal:
    """Proposal to mutate or inject configuration flags into a session."""

    source: str
    requested_flags: dict[str, str]
    explicit_user_approved: bool = False
    rationale: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class ConfigDriftDetail:
    """Detailed observation of a detected configuration drift or injection."""

    flag_key: str
    baseline_value: str
    observed_value: str
    drift_reason: str


@dataclass
class PoisonDiagnosisReport:
    """Diagnostic report produced by the poison watchdog."""

    session_id: str
    severity: PoisonSeverity
    detected_drifts: list[ConfigDriftDetail]
    offending_flags: list[str]
    recommendation: str
    evaluated_at: float = field(default_factory=time.time)


@dataclass
class AntidoteReceipt:
    """Receipt generated upon successful execution of 1-Click Antidote."""

    session_id: str
    purged_flags: list[str]
    restored_flags_count: int
    preserved_turns_count: int
    restored_to_checksum: str
    antidote_applied_at: float = field(default_factory=time.time)


@dataclass
class SessionAntidoteConfig:
    """Runtime configuration for anti-poisoning engine and watchdog."""

    allowed_autonomous_flags: set[str] = field(
        default_factory=lambda: {"log_level", "output_format", "concise_mode"}
    )
    blocked_dangerous_flags: set[str] = field(
        default_factory=lambda: {
            "fast_ultra_mode",
            "skip_all_safety_checks",
            "disable_tool_sandboxing",
            "bypass_approval_gate",
            "unrestricted_code_execution",
        }
    )
    max_drift_tolerance: int = 3
    quarantine_suspicious_turns: bool = True
