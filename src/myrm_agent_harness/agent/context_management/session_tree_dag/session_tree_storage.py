"""Storage engine managing append-only JSONL entries and fast lineage path traversal.

[INPUT]
- agent.context_management.session_tree_dag.session_tree_dag_types::DagEntryKind, SessionTreeEntry (POS: Types
  and data structures for immutable append-only session tree DAG and branching.)

[OUTPUT]
- SessionTreeStorage: Handles append-only line-based persistence and in-memory DAG topology navigation.

[POS]
Storage engine managing append-only JSONL entries and fast lineage path traversal.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from .session_tree_dag_types import DagEntryKind, SessionTreeEntry


class SessionTreeStorage:
    """Handles append-only line-based persistence and in-memory DAG topology navigation."""

    def __init__(self, persistence_file_path: Optional[str] = None) -> None:
        self._file_path = persistence_file_path
        self._entries_by_id: Dict[str, SessionTreeEntry] = {}
        self._children_by_parent: Dict[str, List[str]] = {}
        self._append_log_lines: List[str] = []

    def append_entry(self, entry: SessionTreeEntry) -> None:
        """Append an entry to in-memory DAG and optional line-based JSONL log file."""
        if entry.entry_id in self._entries_by_id:
            raise ValueError(f"Duplicate entry_id {entry.entry_id} in session tree")

        # Cycle check
        if entry.parent_id == entry.entry_id:
            raise ValueError("Entry cannot be its own parent")

        self._entries_by_id[entry.entry_id] = entry

        parent_key = entry.parent_id or "ROOT"
        if parent_key not in self._children_by_parent:
            self._children_by_parent[parent_key] = []
        self._children_by_parent[parent_key].append(entry.entry_id)

        # JSONL serialization
        row_dict = {
            "entry_id": entry.entry_id,
            "parent_id": entry.parent_id,
            "kind": entry.kind.value,
            "session_id": entry.session_id,
            "branch_name": entry.branch_name,
            "created_at_iso": entry.created_at_iso,
            "payload": entry.payload,
            "entry_hash": entry.entry_hash,
        }
        line = json.dumps(row_dict, ensure_ascii=False)
        self._append_log_lines.append(line)

        if self._file_path:
            p = Path(self._file_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def get_entry(self, entry_id: str) -> Optional[SessionTreeEntry]:
        """Fetch single entry by ID."""
        return self._entries_by_id.get(entry_id)

    def get_children(self, entry_id: Optional[str]) -> List[str]:
        """Fetch direct child entry IDs."""
        key = entry_id or "ROOT"
        return list(self._children_by_parent.get(key, []))

    def get_lineage_path(self, target_entry_id: str) -> List[SessionTreeEntry]:
        """Trace lineage backwards from target_entry_id to root and reverse to root-first order."""
        path: List[SessionTreeEntry] = []
        visited = set()
        curr_id: Optional[str] = target_entry_id

        while curr_id is not None:
            if curr_id in visited:
                raise RuntimeError(f"Cyclic dependency detected at node {curr_id}")
            visited.add(curr_id)

            entry = self._entries_by_id.get(curr_id)
            if entry is None:
                raise KeyError(f"Missing referenced parent entry {curr_id} in tree")

            path.append(entry)
            curr_id = entry.parent_id

        # Reverse to return Root -> ... -> Target
        return list(reversed(path))

    def get_all_entries(self) -> List[SessionTreeEntry]:
        """Return all recorded entries."""
        return list(self._entries_by_id.values())

    def get_raw_jsonl_lines(self) -> List[str]:
        """Return raw appended JSONL lines."""
        return list(self._append_log_lines)

    @property
    def persistence_file_path(self) -> Optional[str]:
        """Return persistence file path if configured."""
        return self._file_path

    def squash_and_rewrite(self, retained_entries: List[SessionTreeEntry]) -> None:
        """Atomically compact and rewrite in-memory entries and on-disk JSONL log."""
        self._entries_by_id = {e.entry_id: e for e in retained_entries}
        self._children_by_parent = {}
        for entry in retained_entries:
            parent_key = entry.parent_id or "ROOT"
            if parent_key not in self._children_by_parent:
                self._children_by_parent[parent_key] = []
            self._children_by_parent[parent_key].append(entry.entry_id)

        self._append_log_lines = []
        for entry in retained_entries:
            row_dict = {
                "entry_id": entry.entry_id,
                "parent_id": entry.parent_id,
                "kind": entry.kind.value,
                "session_id": entry.session_id,
                "branch_name": entry.branch_name,
                "created_at_iso": entry.created_at_iso,
                "payload": entry.payload,
                "entry_hash": entry.entry_hash,
            }
            self._append_log_lines.append(json.dumps(row_dict, ensure_ascii=False))

        if self._file_path:
            p = Path(self._file_path)
            tmp_p = p.with_name(f".{p.name}.gctmp")
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp_p, "w", encoding="utf-8") as f:
                for line in self._append_log_lines:
                    f.write(line + "\n")
            tmp_p.replace(p)
