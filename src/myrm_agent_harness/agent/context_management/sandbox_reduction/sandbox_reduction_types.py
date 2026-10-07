"""Strongly typed contracts for In-Sandbox Data Reduction and Session Action Ledger (Item 221).

[INPUT]
- None (self-contained, standard library only).

[OUTPUT]
- ReductionKind: Operational classification of in-sandbox data truncation or aggregation.
- ActionKind: Semantic category of recorded execution actions (file edit, command, test, error).
- ReducedOutputEnvelope: High signal-to-noise structured outcome replacing bulky raw outputs.
- ActionLedgerEntry: Strongly typed execution transaction capturing atomic edits, commands, and errors.
- LedgerQueryResult: Post-compaction retrieval result containing matched entries and compact report.
- SandboxReductionConfig: Tunable configuration limits for sampling, truncation, and persistence.

[POS]
- Eliminates context blowout from voluminous raw outputs (80%+ reduction) while retaining
- 100% fine-grained file diffs, command exit codes, and error traces across compaction via SQLite.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class ReductionKind(str, enum.Enum):
    """Classification of data distillation strategy applied within sandbox."""

    LOG_TRUNCATION = "log_truncation"
    DIFF_SUMMARY = "diff_summary"
    STATISTICAL_HISTOGRAM = "statistical_histogram"
    SCRIPT_AGGREGATION = "script_aggregation"


class ActionKind(str, enum.Enum):
    """Semantic category of fine-grained session actions."""

    FILE_EDIT = "file_edit"
    COMMAND_EXECUTION = "command_execution"
    TEST_RUN = "test_run"
    ERROR_OCCURRENCE = "error_occurrence"


@dataclass(frozen=True, slots=True)
class ReducedOutputEnvelope:
    """High signal-to-noise payload distilled in-sandbox to prevent raw output context blowout."""

    kind: ReductionKind
    original_bytes: int
    reduced_bytes: int
    reduction_ratio: float
    sample_lines: list[str]
    summary_text: str

    def to_dict(self) -> dict[str, object]:
        """Serializes reduced output envelope to dictionary."""
        return {
            "kind": self.kind.value,
            "original_bytes": self.original_bytes,
            "reduced_bytes": self.reduced_bytes,
            "reduction_ratio": self.reduction_ratio,
            "sample_lines": list(self.sample_lines),
            "summary_text": self.summary_text,
        }


@dataclass(slots=True)
class ActionLedgerEntry:
    """Atomic execution transaction recorded in the session ledger for post-compaction lookup."""

    action_id: str
    session_id: str
    turn_id: str
    action_kind: ActionKind
    tool_name: str
    timestamp: float = field(default_factory=time.time)
    target_path: str | None = None
    command_snippet: str | None = None
    diff_summary: str | None = None
    exit_code: int | None = None
    error_evidence: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Serializes action ledger entry to dictionary."""
        return {
            "action_id": self.action_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "action_kind": self.action_kind.value,
            "tool_name": self.tool_name,
            "timestamp": self.timestamp,
            "target_path": self.target_path,
            "command_snippet": self.command_snippet,
            "diff_summary": self.diff_summary,
            "exit_code": self.exit_code,
            "error_evidence": self.error_evidence,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class LedgerQueryResult:
    """Structured query result recovering precise historical actions post-compaction."""

    session_id: str
    total_matched: int
    entries: list[ActionLedgerEntry]
    compact_report: str

    def to_dict(self) -> dict[str, object]:
        """Serializes query outcome to dictionary."""
        return {
            "session_id": self.session_id,
            "total_matched": self.total_matched,
            "entries": [e.to_dict() for e in self.entries],
            "compact_report": self.compact_report,
        }


@dataclass(frozen=True, slots=True)
class SandboxReductionConfig:
    """Tunable thresholds and persistence settings for in-sandbox reduction and action ledger."""

    max_sample_lines: int = 20
    max_diff_lines: int = 30
    sqlite_path: str = ":memory:"
    enable_sqlite_persistence: bool = True
    max_cached_entries_per_session: int = 1000
