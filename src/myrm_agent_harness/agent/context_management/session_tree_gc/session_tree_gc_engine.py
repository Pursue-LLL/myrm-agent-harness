"""Engine executing topological dead branch prune and physical storage compaction.

[INPUT]
- tree_suite: SessionTreeDagSuite logical exploration tree
- branch_name: str target exploration branch to prune
- force: bool whether to bypass summary anchor check

[OUTPUT]
- SessionTreeGcEngine: Engine class providing topological prune analysis and physical compaction.

[POS]
Engine executing topological dead branch prune and physical storage compaction.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from ..session_tree_dag import DagEntryKind, SessionTreeDagSuite, SessionTreeEntry
from .gc_types import GcSafetyRule, PrunedBranchReport, StorageGcReceipt


class SessionTreeGcEngine:
    """Performs topological analysis, safety rule enforcement, and on-disk JSONL compaction."""

    PROTECTED_BRANCHES: Set[str] = {"main", "master"}

    @classmethod
    def get_prunable_branches(
        cls,
        tree_suite: SessionTreeDagSuite,
    ) -> List[str]:
        """Return list of exploration branches eligible for pruning (excluding active head and protected root)."""
        active = tree_suite.active_branch_name
        all_branches = tree_suite.list_branches()
        candidates: List[str] = []
        for b in all_branches:
            if b.branch_name != active and b.branch_name not in cls.PROTECTED_BRANCHES:
                candidates.append(b.branch_name)
        return candidates

    @classmethod
    def check_has_summary_anchor(
        cls,
        tree_suite: SessionTreeDagSuite,
        branch_name: str,
    ) -> bool:
        """Verify whether target branch has deposited an anchored summary in active/main lineage."""
        all_entries = tree_suite.get_storage().get_all_entries()
        for entry in all_entries:
            if entry.branch_name in cls.PROTECTED_BRANCHES:
                payload_str = str(entry.payload)
                if branch_name in payload_str or entry.payload.get("source_branch") == branch_name:
                    return True
        return False

    @classmethod
    def collect_exclusive_branch_entries(
        cls,
        tree_suite: SessionTreeDagSuite,
        branch_name: str,
    ) -> List[SessionTreeEntry]:
        """Identify node entries exclusively belonging to target branch and not part of retained branches."""
        storage = tree_suite.get_storage()
        all_entries = storage.get_all_entries()

        # Find entry ids referenced by other retained branches
        other_branch_entry_ids: Set[str] = set()
        for b in tree_suite.list_branches():
            if b.branch_name != branch_name and b.head_entry_id:
                try:
                    lineage = storage.get_lineage_path(b.head_entry_id)
                    for e in lineage:
                        other_branch_entry_ids.add(e.entry_id)
                except KeyError:
                    pass

        # Exclusive candidates: entries created under branch_name not present in other lineages
        exclusive: List[SessionTreeEntry] = []
        for e in all_entries:
            if e.branch_name == branch_name and e.entry_id not in other_branch_entry_ids:
                exclusive.append(e)

        return exclusive

    @classmethod
    def execute_prune_and_squash(
        cls,
        tree_suite: SessionTreeDagSuite,
        branches_to_prune: List[str],
        require_summary_anchor: bool = False,
        force: bool = False,
    ) -> StorageGcReceipt:
        """Atomically prune branches, update memory DAG, and squash physical storage."""
        storage = tree_suite.get_storage()
        all_entries = storage.get_all_entries()
        before_count = len(all_entries)

        file_path = storage.persistence_file_path
        before_bytes = Path(file_path).stat().st_size if file_path and Path(file_path).exists() else 0

        entries_to_remove: Set[str] = set()
        for b_name in branches_to_prune:
            if b_name == tree_suite.active_branch_name:
                raise ValueError(f"Cannot prune active exploration branch: '{b_name}'")
            if b_name in cls.PROTECTED_BRANCHES:
                raise ValueError(f"Cannot prune root protected branch: '{b_name}'")

            if require_summary_anchor and not force:
                if not cls.check_has_summary_anchor(tree_suite, b_name):
                    raise RuntimeError(
                        f"Prune blocked: branch '{b_name}' has no permanent summary anchor in main lineage"
                    )

            exclusive_entries = cls.collect_exclusive_branch_entries(tree_suite, b_name)
            for e in exclusive_entries:
                entries_to_remove.add(e.entry_id)

        # Retained entries
        retained = [e for e in all_entries if e.entry_id not in entries_to_remove]
        after_count = len(retained)

        # Remove branch metadata from tree suite
        for b_name in branches_to_prune:
            if b_name in tree_suite._branches:
                del tree_suite._branches[b_name]

        # Squash storage
        storage.squash_and_rewrite(retained)

        after_bytes = Path(file_path).stat().st_size if file_path and Path(file_path).exists() else 0
        freed_bytes = max(0, before_bytes - after_bytes)

        all_hashes = "".join(e.entry_hash for e in retained)
        compaction_hash = hashlib.sha256(
            f"{tree_suite.session_id}:{before_count}:{after_count}:{all_hashes}".encode("utf-8")
        ).hexdigest()[:16]

        retained_branch_names = [b.branch_name for b in tree_suite.list_branches()]

        return StorageGcReceipt(
            receipt_id=f"sgc_{hashlib.sha256(compaction_hash.encode()).hexdigest()[:8]}",
            session_id=tree_suite.session_id,
            before_entries_count=before_count,
            after_entries_count=after_count,
            purged_entries_count=before_count - after_count,
            pruned_branches=list(branches_to_prune),
            retained_branches=retained_branch_names,
            before_storage_bytes=before_bytes,
            after_storage_bytes=after_bytes,
            freed_storage_bytes=freed_bytes,
            compaction_hash=compaction_hash,
            completed_at_iso=datetime.now(timezone.utc).isoformat(),
        )
