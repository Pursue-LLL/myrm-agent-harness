# ============================================================================
# # Project Context Isolation & Objective Recap Types (Item 145)
# # Strict typed contracts for project namespace boundaries, cross-project
# # file reference screening, and objective alignment recap assertions.
# ============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ObjectiveRecapStatus(StrEnum):
    """Execution status for objective recap alignment check."""

    VERIFIED = "verified"  # Project root and objective aligned successfully
    MISMATCH_INTERCEPTED = "mismatch_intercepted"  # Mismatch detected; execution blocked
    BYPASSED = "bypassed"  # Explicit non-ambiguous prompt; recap assertion optional


@dataclass(slots=True)
class ProjectBoundary:
    """Defines the physical project isolation boundary for a session."""

    project_id: str
    workspace_root: str
    project_name: str = ""

    def is_path_within_boundary(self, file_path: str) -> bool:
        """Determines if a given normalized file path belongs within this workspace root."""
        import os

        norm_root = os.path.abspath(self.workspace_root)
        norm_target = os.path.abspath(file_path)
        # Verify norm_target starts with norm_root as directory ancestor
        return norm_target == norm_root or norm_target.startswith(norm_root.rstrip(os.sep) + os.sep)


@dataclass(slots=True)
class CrossProjectCheckResult:
    """Outcome of file reference validation and cross-project leak prevention."""

    is_aligned: bool
    filtered_file_paths: list[str] = field(default_factory=list)
    retained_file_paths: list[str] = field(default_factory=list)
    violation_reason: str | None = None


@dataclass(slots=True)
class ObjectiveRecapAssertion:
    """Assertion contract returned before executing tasks under potential project drift."""

    status: ObjectiveRecapStatus
    project_id: str
    workspace_root: str
    objective_summary: str
    recap_display_badge: str
    is_blocked: bool = False
    warning_message: str | None = None
