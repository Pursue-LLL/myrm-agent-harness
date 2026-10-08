"""Types and data structures for session tree dead branch pruning and physical storage GC.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- GcSafetyRule: Enumeration of safety rules guarding branch pruning.
- PrunedBranchReport: Diagnostic report detailing individual pruned branch metrics.
- StorageGcReceipt: Immutable receipt summarizing garbage collection results and storage compaction.

[POS]
Types and data structures for session tree dead branch pruning and physical storage GC.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class GcSafetyRule(str, Enum):
    """Safety rules governing branch pruning and GC operations."""

    DISALLOW_ACTIVE_BRANCH_PRUNING = "disallow_active_branch_pruning"
    DISALLOW_MAIN_ROOT_PRUNING = "disallow_main_root_pruning"
    REQUIRE_BRANCH_SUMMARY_ANCHOR = "require_branch_summary_anchor"


@dataclass(frozen=True)
class PrunedBranchReport:
    """Report detailing the results of pruning a single exploration branch."""

    branch_name: str
    purged_entries_count: int
    freed_bytes_estimate: int
    had_summary_anchor: bool
    pruned_at_iso: str


@dataclass(frozen=True)
class StorageGcReceipt:
    """Certified cryptographic receipt documenting a complete session tree GC and physical compaction run."""

    receipt_id: str
    session_id: str
    before_entries_count: int
    after_entries_count: int
    purged_entries_count: int
    pruned_branches: List[str]
    retained_branches: List[str]
    before_storage_bytes: int
    after_storage_bytes: int
    freed_storage_bytes: int
    compaction_hash: str
    completed_at_iso: str
