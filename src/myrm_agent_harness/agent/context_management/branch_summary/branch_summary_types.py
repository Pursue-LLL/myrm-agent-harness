"""Strongly typed contracts for Branch Summarization and Selective Merge-Back.

[INPUT]
- None (self-contained, standard library only).

[OUTPUT]
- FileActionKind: Enumeration of file operations detected during branch exploration.
- TrackedFileOperation: Granular trace of an individual file access event.
- BranchFileOperations: Aggregated file tracking footprint with read vs modified separation.
- SelectiveMergePolicy: Policy governing how branch achievements merge back to the parent session.
- BranchMergeConflictWarning: Potential file contention alert between branch and parent session.
- BranchSummaryResult: Complete structured contract of summarized branch outcome and merge-back payload.

[POS]
Defines immutable data models for branch compaction, file footprint tracking, and zero-loss parent merging.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class FileActionKind(str, enum.Enum):
    """Classification of filesystem operations triggered in branch."""

    READ = "read"
    WRITE = "write"
    EDIT = "edit"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class TrackedFileOperation:
    """Granular trace of an individual file access event in a branch turn."""

    path: str
    action: FileActionKind
    tool_name: str
    timestamp: float = field(default_factory=time.time)


@dataclass(slots=True)
class BranchFileOperations:
    """Aggregated file tracking footprint with read-only and modified partitions."""

    read_files: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)

    def format_xml(self) -> str:
        """Formats file operations as structured XML blocks for concise LLM context merging."""
        sections: list[str] = []
        if self.read_files:
            items = "\n".join(f"- {p}" for p in self.read_files)
            sections.append(f"<read-files>\n{items}\n</read-files>")
        if self.modified_files:
            items = "\n".join(f"- {p}" for p in self.modified_files)
            sections.append(f"<modified-files>\n{items}\n</modified-files>")
        return "\n\n".join(sections)

    def to_dict(self) -> dict[str, list[str]]:
        """Serializes file operation lists to dictionary."""
        return {
            "read_files": list(self.read_files),
            "modified_files": list(self.modified_files),
        }


class SelectiveMergePolicy(str, enum.Enum):
    """Policy dictating how branch discoveries and modifications merge back into parent session."""

    FULL_SUMMARY_AND_FILES = "full_summary_and_files"
    SUMMARY_ONLY = "summary_only"
    MODIFIED_FILES_ONLY = "modified_files_only"
    AUDIT_DRY_RUN = "audit_dry_run"


@dataclass(frozen=True, slots=True)
class BranchMergeConflictWarning:
    """Alert regarding potential file contention between parent updates and branch edits."""

    file_path: str
    parent_modified: bool
    branch_modified: bool
    severity: str
    resolution_hint: str


@dataclass(slots=True)
class BranchSummaryResult:
    """Complete structured distillation of branch exploration ready for parent merge-back."""

    branch_id: str
    parent_session_id: str
    common_ancestor_turn_id: str
    summary_text: str
    file_operations: BranchFileOperations
    merge_policy: SelectiveMergePolicy
    conflict_warnings: list[BranchMergeConflictWarning] = field(default_factory=list)
    injection_message_text: str = ""
    token_count_estimated: int = 0
    branch_turns_count: int = 0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        """Serializes result into JSON-compatible dictionary."""
        return {
            "branch_id": self.branch_id,
            "parent_session_id": self.parent_session_id,
            "common_ancestor_turn_id": self.common_ancestor_turn_id,
            "summary_text": self.summary_text,
            "file_operations": self.file_operations.to_dict(),
            "merge_policy": self.merge_policy.value,
            "conflict_warnings": [
                {
                    "file_path": w.file_path,
                    "parent_modified": w.parent_modified,
                    "branch_modified": w.branch_modified,
                    "severity": w.severity,
                    "resolution_hint": w.resolution_hint,
                }
                for w in self.conflict_warnings
            ],
            "injection_message_text": self.injection_message_text,
            "token_count_estimated": self.token_count_estimated,
            "branch_turns_count": self.branch_turns_count,
            "created_at": self.created_at,
        }
