"""Main orchestration suite managing immutable session tree DAG and branching exploration.

[INPUT]
- agent.context_management.session_tree_dag.session_tree_dag_types::DagEntryKind, SessionBranchMeta,
  SessionTreeDagReceipt, SessionTreeEntry (POS: Types and data structures for immutable append-only session
  tree DAG and branching.)
- agent.context_management.session_tree_dag.session_tree_storage::SessionTreeStorage (POS: Storage engine
  managing append-only JSONL entries and fast lineage path traversal.)

[OUTPUT]
- SessionTreeDagSuite: Manages immutable append-only session tree DAG and branches for zero-pollution
  exploration.

[POS]
Main orchestration suite managing immutable session tree DAG and branching exploration.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional
import uuid

from .session_tree_dag_types import (
    DagEntryKind,
    SessionBranchMeta,
    SessionTreeDagReceipt,
    SessionTreeEntry,
)
from .session_tree_storage import SessionTreeStorage


class SessionTreeDagSuite:
    """Manages immutable append-only session tree DAG and branches for zero-pollution exploration."""

    def __init__(self, session_id: str, persistence_file_path: Optional[str] = None) -> None:
        self._session_id = session_id
        self._storage = SessionTreeStorage(persistence_file_path=persistence_file_path)
        self._branches: Dict[str, SessionBranchMeta] = {}
        self._active_branch_name = "main"

        # Initialize main branch placeholder
        self._branches["main"] = SessionBranchMeta(
            branch_id="branch_main",
            branch_name="main",
            fork_from_entry_id=None,
            head_entry_id="",
            is_active=True,
        )

    @property
    def session_id(self) -> str:
        """Return session ID."""
        return self._session_id

    @property
    def active_branch_name(self) -> str:
        """Return currently active branch name."""
        return self._active_branch_name

    def _generate_entry_hash(
        self,
        entry_id: str,
        parent_id: Optional[str],
        kind: DagEntryKind,
        payload: Dict[str, str],
        created_at_iso: str,
    ) -> str:
        """Deterministic sha256 checksum for immutable entry node."""
        payload_str = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        content = f"{entry_id}:{parent_id or ''}:{kind.value}:{payload_str}:{created_at_iso}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def _append_entry_internal(
        self,
        kind: DagEntryKind,
        payload: Dict[str, str],
        entry_id: Optional[str] = None,
    ) -> SessionTreeEntry:
        """Internal helper to construct, hash, persist node and advance active branch head."""
        active_branch = self._branches[self._active_branch_name]
        parent_id = active_branch.head_entry_id if active_branch.head_entry_id else None

        actual_id = entry_id or f"node_{uuid.uuid4().hex[:12]}"
        created_at = datetime.now(timezone.utc).isoformat()
        entry_hash = self._generate_entry_hash(actual_id, parent_id, kind, payload, created_at)

        entry = SessionTreeEntry(
            entry_id=actual_id,
            parent_id=parent_id,
            kind=kind,
            session_id=self._session_id,
            branch_name=self._active_branch_name,
            created_at_iso=created_at,
            payload=payload,
            entry_hash=entry_hash,
        )

        self._storage.append_entry(entry)

        # Update active branch head
        self._branches[self._active_branch_name] = SessionBranchMeta(
            branch_id=active_branch.branch_id,
            branch_name=active_branch.branch_name,
            fork_from_entry_id=active_branch.fork_from_entry_id,
            head_entry_id=actual_id,
            is_active=True,
        )

        return entry

    def append_message(
        self,
        role: str,
        content: str,
        entry_id: Optional[str] = None,
    ) -> SessionTreeEntry:
        """Append standard chat/turn message to current branch."""
        payload = {"role": role, "content": content}
        return self._append_entry_internal(DagEntryKind.MESSAGE, payload, entry_id)

    def append_model_switch(
        self,
        model_name: str,
        provider: str,
        reason: str = "",
        entry_id: Optional[str] = None,
    ) -> SessionTreeEntry:
        """First-class event recording model switch."""
        payload = {"model_name": model_name, "provider": provider, "reason": reason}
        return self._append_entry_internal(DagEntryKind.MODEL_SWITCH, payload, entry_id)

    def append_thinking_level_switch(
        self,
        level: str,
        budget_tokens: int,
        entry_id: Optional[str] = None,
    ) -> SessionTreeEntry:
        """First-class event recording reasoning/thinking level adjustment."""
        payload = {"level": level, "budget_tokens": str(budget_tokens)}
        return self._append_entry_internal(DagEntryKind.THINKING_LEVEL_SWITCH, payload, entry_id)

    def append_compaction_snapshot(
        self,
        summary_text: str,
        compacted_up_to_entry_id: str,
        entry_id: Optional[str] = None,
    ) -> SessionTreeEntry:
        """First-class event recording compaction snapshot."""
        payload = {
            "summary_text": summary_text,
            "compacted_up_to_entry_id": compacted_up_to_entry_id,
        }
        return self._append_entry_internal(DagEntryKind.COMPACTION_SNAPSHOT, payload, entry_id)

    def fork_branch(
        self,
        new_branch_name: str,
        from_entry_id: Optional[str] = None,
    ) -> SessionBranchMeta:
        """Fork a new exploration branch from any historical entry node or current active head."""
        if new_branch_name in self._branches:
            raise ValueError(f"Branch '{new_branch_name}' already exists")

        active_meta = self._branches[self._active_branch_name]
        target_fork_id = from_entry_id if from_entry_id is not None else active_meta.head_entry_id

        if target_fork_id:
            entry = self._storage.get_entry(target_fork_id)
            if entry is None:
                raise KeyError(f"Target fork entry '{target_fork_id}' not found in DAG")

        branch_meta = SessionBranchMeta(
            branch_id=f"branch_{uuid.uuid4().hex[:8]}",
            branch_name=new_branch_name,
            fork_from_entry_id=target_fork_id,
            head_entry_id=target_fork_id or "",
            is_active=False,
        )
        self._branches[new_branch_name] = branch_meta
        return branch_meta

    def switch_active_branch(self, branch_name: str) -> None:
        """Seamlessly switch active exploration branch for zero-friction time-travel."""
        if branch_name not in self._branches:
            raise KeyError(f"Branch '{branch_name}' does not exist")

        for name, meta in list(self._branches.items()):
            is_active = (name == branch_name)
            self._branches[name] = SessionBranchMeta(
                branch_id=meta.branch_id,
                branch_name=meta.branch_name,
                fork_from_entry_id=meta.fork_from_entry_id,
                head_entry_id=meta.head_entry_id,
                is_active=is_active,
            )
        self._active_branch_name = branch_name

    def get_active_lineage_path(self) -> List[SessionTreeEntry]:
        """Extract ordered linear lineage path from root to current active head."""
        active_meta = self._branches[self._active_branch_name]
        if not active_meta.head_entry_id:
            return []
        return self._storage.get_lineage_path(active_meta.head_entry_id)

    def get_branch(self, branch_name: str) -> Optional[SessionBranchMeta]:
        """Retrieve branch metadata by name."""
        return self._branches.get(branch_name)

    def list_branches(self) -> List[SessionBranchMeta]:
        """List all branches in DAG."""
        return list(self._branches.values())

    def get_storage(self) -> SessionTreeStorage:
        """Access underlying append-only storage engine."""
        return self._storage

    def generate_mermaid_dag(self) -> str:
        """Generate Mermaid flow diagram representation of session DAG."""
        lines: List[str] = ["graph TD"]
        entries = self._storage.get_all_entries()

        for entry in entries:
            kind_tag = entry.kind.value
            node_label = f"{entry.entry_id}[{entry.branch_name}: {kind_tag}]"
            lines.append(f"    {node_label}")
            if entry.parent_id:
                lines.append(f"    {entry.parent_id} --> {entry.entry_id}")

        return "\n".join(lines)

    def export_topology_graph(self) -> Dict[str, List[str]]:
        """Export parent -> children adjacency list representation."""
        entries = self._storage.get_all_entries()
        adj: Dict[str, List[str]] = {}
        for entry in entries:
            parent_key = entry.parent_id or "ROOT"
            if parent_key not in adj:
                adj[parent_key] = []
            adj[parent_key].append(entry.entry_id)
        return adj

    def issue_dag_receipt(self) -> SessionTreeDagReceipt:
        """Issue cryptographic receipt verifying DAG integrity and active lineage count."""
        entries = self._storage.get_all_entries()
        linear_path = self.get_active_lineage_path()
        active_meta = self._branches[self._active_branch_name]

        all_hashes = "".join(e.entry_hash for e in entries)
        dag_hash = hashlib.sha256(all_hashes.encode("utf-8")).hexdigest()[:16]

        return SessionTreeDagReceipt(
            session_id=self._session_id,
            total_entries_count=len(entries),
            active_branch_name=self._active_branch_name,
            branches_count=len(self._branches),
            linear_path_entries_count=len(linear_path),
            active_head_entry_id=active_meta.head_entry_id,
            dag_hash=dag_hash,
        )
