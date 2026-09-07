"""Core types and data models for Agentic Codebase Slimming Pipeline.

[INPUT]
- (none)

[OUTPUT]
- DeadCodeCandidate: Identified dead or redundant code target.
- DeadCodeScanReport: Aggregated report of dead code candidates.
- SlimmingTaskStatus: Status enum for slimming subagent execution.
- SlimmingModuleTask: Single module refactoring task definition.
- EquivalenceVerdict: Invariance assertion result from regression tests.
- SlimmingLedger: Quantitative accounting of lines cut, token saved, and commits.

[POS]
Data structures and protocols for automated codebase slimming.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class SlimmingRiskLevel(str, Enum):
    """Safety and risk assessment level for a slimming candidate."""

    SAFE = "safe"          # Unused internal private function, unreachable branch, dead test file
    MODERATE = "moderate"  # Unused public function/class with zero local references
    AGGRESSIVE = "aggressive"  # Redundant wrapper/abstraction requiring interface merging


class SlimmingTaskStatus(str, Enum):
    """Execution status for a subagent slimming wave."""

    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class DeadCodeCandidate:
    """A single candidate location identified for dead code pruning or refactoring."""

    file_path: str
    symbol_name: str
    line_start: int
    line_end: int
    risk_level: SlimmingRiskLevel
    reason: str
    estimated_lines_cut: int = 0


@dataclass(frozen=True, slots=True)
class DeadCodeScanReport:
    """Aggregated scan report containing identified pruning candidates."""

    candidates: tuple[DeadCodeCandidate, ...] = field(default_factory=tuple)
    total_estimated_lines_cut: int = 0
    scanned_files_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "total_candidates": len(self.candidates),
            "total_estimated_lines_cut": self.total_estimated_lines_cut,
            "scanned_files_count": self.scanned_files_count,
            "candidates": [
                {
                    "file_path": c.file_path,
                    "symbol_name": c.symbol_name,
                    "lines": f"{c.line_start}-{c.line_end}",
                    "risk_level": c.risk_level.value,
                    "reason": c.reason,
                    "estimated_lines_cut": c.estimated_lines_cut,
                }
                for c in self.candidates
            ],
        }


@dataclass(frozen=True, slots=True)
class EquivalenceVerdict:
    """Assertion verdict confirming behavior invariance after refactoring."""

    passed: bool
    test_command: str
    exit_code: int
    output_summary: str
    failure_reason: str = ""


@dataclass(frozen=True, slots=True)
class SlimmingModuleTask:
    """A discrete slimming subtask assigned to an isolated worktree subagent."""

    task_id: str
    module_path: str
    candidates: tuple[DeadCodeCandidate, ...]
    test_command: str = "pytest"
    status: SlimmingTaskStatus = SlimmingTaskStatus.PENDING
    actual_lines_cut: int = 0
    error_message: str = ""


@dataclass(slots=True)
class SlimmingLedger:
    """Financial and engineering ledger tracking lines cut and token efficiency."""

    total_tasks: int = 0
    successful_tasks: int = 0
    rolled_back_tasks: int = 0
    lines_cut: int = 0
    estimated_token_context_saved: int = 0
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "total_tasks": self.total_tasks,
            "successful_tasks": self.successful_tasks,
            "rolled_back_tasks": self.rolled_back_tasks,
            "lines_cut": self.lines_cut,
            "estimated_token_context_saved": self.estimated_token_context_saved,
            "duration_seconds": round(self.duration_seconds, 2),
            "success_rate": f"{(self.successful_tasks / max(1, self.total_tasks)) * 100:.1f}%",
        }
