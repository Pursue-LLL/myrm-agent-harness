"""Types and data structures for immutable append-only session tree DAG and branching.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- DagEntryKind: Classification of first-class immutable entries within the session tree DAG.
- SessionTreeEntry: Immutable node entry within the session tree DAG carrying explicit parent pointer.
- SessionBranchMeta: Metadata describing an exploration branch in the tree DAG.
- SessionTreeDagReceipt: Receipt summarizing DAG structure, active lineage path, and tree integrity.

[POS]
Types and data structures for immutable append-only session tree DAG and branching.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class DagEntryKind(str, Enum):
    """Classification of first-class immutable entries within the session tree DAG."""

    MESSAGE = "message"
    MODEL_SWITCH = "model_switch"
    THINKING_LEVEL_SWITCH = "thinking_level_switch"
    COMPACTION_SNAPSHOT = "compaction_snapshot"
    BRANCH_MERGE = "branch_merge"
    CHECKPOINT = "checkpoint"


@dataclass(frozen=True)
class SessionTreeEntry:
    """Immutable node entry within the session tree DAG carrying explicit parent pointer."""

    entry_id: str
    parent_id: Optional[str]
    kind: DagEntryKind
    session_id: str
    branch_name: str
    created_at_iso: str
    payload: Dict[str, str] = field(default_factory=dict)
    entry_hash: str = ""


@dataclass(frozen=True)
class SessionBranchMeta:
    """Metadata describing an exploration branch in the tree DAG."""

    branch_id: str
    branch_name: str
    fork_from_entry_id: Optional[str]
    head_entry_id: str
    is_active: bool = False


@dataclass(frozen=True)
class SessionTreeDagReceipt:
    """Receipt summarizing DAG structure, active lineage path, and tree integrity."""

    session_id: str
    total_entries_count: int
    active_branch_name: str
    branches_count: int
    linear_path_entries_count: int
    active_head_entry_id: str
    dag_hash: str
