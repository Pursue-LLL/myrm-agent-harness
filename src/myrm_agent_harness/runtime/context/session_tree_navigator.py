"""Session Tree Navigator and Time-Travel Branch Manager (Pi Harness v2).

Implements the Pi Harness v2 session tree architecture:
1. Append-Only Conversation Tree:
   Every session entry holds entry_id and parent_id (root has None), stored linearly
   in a single append-only journal file without external file pollution.
2. Time-Travel Navigation (navigateTree):
   Instantly teleports the active leaf pointer to any historical node:
   - For user message targets: active leaf reverts to target's parent, returning
     the target content as editor_text for seamless edit-resend.
   - For non-user targets: active leaf points directly to target.
3. Branch Summarization (branchSummary):
   When switching away from an abandoned branch with summarize=True, computes the
   Lowest Common Ancestor (LCA), collects abandoned entries, and injects a
   BranchSummaryEntry at the destination position to retain context insights.
4. Tree Projection (getTree & getBranch):
   Reconstructs the hierarchical multi-branch DAG and extracts active branch paths.

[INPUT]
- target_id: str
- summarize: bool
- summary_text: str | None
- label: str | None

[OUTPUT]
- SessionEntryType
- SessionTreeNodeEntry
- BranchSummaryPayload
- NavigateTreeResult
- SessionTreeNode
- SessionTreeNavigator

[POS]
Harness runtime context layer. Delivers audit-grade conversation branching,
time travel navigation, and branch summary reconciliation.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class SessionEntryType(StrEnum):
    """Discriminant types for session tree entries."""

    MESSAGE = "message"
    COMPACTION = "compaction"
    BRANCH_SUMMARY = "branch_summary"
    CUSTOM = "custom"
    LABEL = "label"
    MODEL_CHANGE = "model_change"
    THINKING_LEVEL_CHANGE = "thinking_level_change"


@dataclass(slots=True, frozen=True)
class SessionTreeNodeEntry:
    """An immutable node in the append-only conversation tree."""

    entry_id: str
    parent_id: str | None
    entry_type: SessionEntryType
    role: str | None = None
    content: str = ""
    timestamp_ms: int = 0
    details: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Serialize entry to dictionary."""
        return {
            "entry_id": self.entry_id,
            "parent_id": self.parent_id,
            "entry_type": self.entry_type.value,
            "role": self.role,
            "content": self.content,
            "timestamp_ms": self.timestamp_ms,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> SessionTreeNodeEntry:
        """Deserialize entry from dictionary."""
        det_raw = data.get("details")
        det_dict: dict[str, str] = (
            {str(k): str(v) for k, v in det_raw.items()}
            if isinstance(det_raw, dict)
            else {}
        )
        return cls(
            entry_id=str(data["entry_id"]),
            parent_id=str(data["parent_id"]) if data.get("parent_id") is not None else None,
            entry_type=SessionEntryType(str(data["entry_type"])),
            role=str(data["role"]) if data.get("role") is not None else None,
            content=str(data.get("content", "")),
            timestamp_ms=int(str(data.get("timestamp_ms", 0))),
            details=det_dict,
        )


@dataclass(slots=True, frozen=True)
class BranchSummaryPayload:
    """Metadata attached to a branch summary entry."""

    from_id: str
    target_id: str
    summary_text: str
    abandoned_count: int
    common_ancestor_id: str | None
    usage_tokens: int = 0
    cost_usd: float = 0.0


@dataclass(slots=True, frozen=True)
class NavigateTreeResult:
    """Result returned by a time-travel navigation operation."""

    target_id: str
    old_leaf_id: str | None
    new_leaf_id: str | None
    editor_text: str | None
    common_ancestor_id: str | None
    abandoned_entries_count: int
    summary_entry: SessionTreeNodeEntry | None = None
    is_noop: bool = False


@dataclass(slots=True)
class SessionTreeNode:
    """Hierarchical tree representation for UI or visual rendering."""

    entry: SessionTreeNodeEntry
    children: list[SessionTreeNode] = field(default_factory=list)


class SessionTreeNavigator:
    """Thread-safe append-only session tree manager with time-travel navigation."""

    def __init__(self, journal_path: Path | str | None = None) -> None:
        self._journal_path = Path(journal_path) if journal_path is not None else None
        self._lock = threading.RLock()
        self._entries: list[SessionTreeNodeEntry] = []
        self._by_id: dict[str, SessionTreeNodeEntry] = {}
        self._children_map: dict[str | None, list[str]] = {}
        self._current_leaf_id: str | None = None

        if self._journal_path and self._journal_path.exists():
            self._resurrect_from_journal()

    def _append_to_disk(self, item: SessionTreeNodeEntry) -> None:
        """Write item line to journal file."""
        if self._journal_path is None:
            return
        self._journal_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(item.to_dict(), ensure_ascii=False) + "\n"
        with self._journal_path.open("a", encoding="utf-8") as f:
            f.write(line)

    def _resurrect_from_journal(self) -> None:
        """Reconstruct tree from journal file."""
        if self._journal_path is None or not self._journal_path.exists():
            return

        with self._journal_path.open("r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    data = json.loads(stripped)
                    entry = SessionTreeNodeEntry.from_dict(data)
                    self._register_entry_in_memory(entry, advance_leaf=True)
                except Exception:
                    continue

    def _register_entry_in_memory(
        self,
        entry: SessionTreeNodeEntry,
        advance_leaf: bool = True,
    ) -> None:
        """Register entry into memory indexing structures."""
        self._entries.append(entry)
        self._by_id[entry.entry_id] = entry
        parent_id = entry.parent_id
        if parent_id not in self._children_map:
            self._children_map[parent_id] = []
        self._children_map[parent_id].append(entry.entry_id)
        if advance_leaf:
            self._current_leaf_id = entry.entry_id

    def append_entry(
        self,
        *,
        entry_type: SessionEntryType,
        content: str = "",
        role: str | None = None,
        parent_id: str | None = None,
        details: dict[str, str] | None = None,
    ) -> SessionTreeNodeEntry:
        """Append a new node to the tree, advancing the current leaf pointer."""
        with self._lock:
            # If parent_id not explicitly given, attach to current leaf
            resolved_parent = parent_id if parent_id is not None else self._current_leaf_id
            if resolved_parent is not None and resolved_parent not in self._by_id:
                raise KeyError(f"Parent entry {resolved_parent} does not exist in tree.")

            entry = SessionTreeNodeEntry(
                entry_id=f"entry-{uuid.uuid4().hex[:12]}",
                parent_id=resolved_parent,
                entry_type=entry_type,
                role=role,
                content=content,
                timestamp_ms=int(time.time() * 1000),
                details=dict(details or {}),
            )
            self._append_to_disk(entry)
            self._register_entry_in_memory(entry, advance_leaf=True)
            return entry

    def get_leaf_id(self) -> str | None:
        """Return the ID of current active leaf entry."""
        with self._lock:
            return self._current_leaf_id

    def get_entry(self, entry_id: str) -> SessionTreeNodeEntry | None:
        """Look up an entry by ID."""
        with self._lock:
            return self._by_id.get(entry_id)

    def get_branch(self, leaf_id: str | None = None) -> list[SessionTreeNodeEntry]:
        """Return the chronological root-to-leaf path for the specified or current leaf."""
        with self._lock:
            active_leaf = leaf_id if leaf_id is not None else self._current_leaf_id
            if active_leaf is None:
                return []
            if active_leaf not in self._by_id:
                raise KeyError(f"Leaf entry {active_leaf} not found.")

            path: list[SessionTreeNodeEntry] = []
            curr: str | None = active_leaf
            visited: set[str] = set()

            while curr is not None and curr in self._by_id and curr not in visited:
                visited.add(curr)
                node = self._by_id[curr]
                path.append(node)
                curr = node.parent_id

            path.reverse()
            return path

    def collect_abandoned_branch(
        self,
        target_id: str,
    ) -> tuple[list[SessionTreeNodeEntry], str | None]:
        """Identify abandoned entries between current leaf and target, returning LCA."""
        with self._lock:
            if self._current_leaf_id is None:
                return [], None
            if target_id not in self._by_id:
                raise KeyError(f"Target entry {target_id} not found.")

            old_branch = self.get_branch(self._current_leaf_id)
            target_branch = self.get_branch(target_id)
            old_set = {e.entry_id for e in old_branch}

            common_ancestor_id: str | None = None
            for e in reversed(target_branch):
                if e.entry_id in old_set:
                    common_ancestor_id = e.entry_id
                    break

            abandoned: list[SessionTreeNodeEntry] = []
            curr: str | None = self._current_leaf_id
            visited: set[str] = set()

            while curr and curr != common_ancestor_id and curr in self._by_id and curr not in visited:
                visited.add(curr)
                node = self._by_id[curr]
                abandoned.append(node)
                curr = node.parent_id

            abandoned.reverse()
            return abandoned, common_ancestor_id

    def navigate_tree(
        self,
        target_id: str,
        *,
        summarize: bool = False,
        summary_text: str | None = None,
        label: str | None = None,
        usage_tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> NavigateTreeResult:
        """Teleport active leaf pointer to target node with optional branch summary."""
        with self._lock:
            if target_id not in self._by_id:
                raise KeyError(f"Target entry {target_id} not found.")

            old_leaf = self._current_leaf_id
            if old_leaf == target_id:
                return NavigateTreeResult(
                    target_id=target_id,
                    old_leaf_id=old_leaf,
                    new_leaf_id=old_leaf,
                    editor_text=None,
                    common_ancestor_id=target_id,
                    abandoned_entries_count=0,
                    summary_entry=None,
                    is_noop=True,
                )

            abandoned, lca_id = self.collect_abandoned_branch(target_id)
            target_entry = self._by_id[target_id]

            new_leaf_id: str | None
            editor_text: str | None = None

            if target_entry.entry_type == SessionEntryType.MESSAGE and target_entry.role == "user":
                new_leaf_id = target_entry.parent_id
                editor_text = target_entry.content
            else:
                new_leaf_id = target_id

            summary_node: SessionTreeNodeEntry | None = None
            if summarize and abandoned and summary_text:
                summary_details = {
                    "from_id": str(old_leaf),
                    "target_id": str(target_id),
                    "common_ancestor_id": str(lca_id or ""),
                    "abandoned_count": str(len(abandoned)),
                    "usage_tokens": str(usage_tokens),
                    "cost_usd": str(cost_usd),
                }
                if label:
                    summary_details["label"] = label

                summary_node = self.append_entry(
                    entry_type=SessionEntryType.BRANCH_SUMMARY,
                    content=summary_text,
                    parent_id=new_leaf_id,
                    details=summary_details,
                )
                self._current_leaf_id = summary_node.entry_id
            else:
                self._current_leaf_id = new_leaf_id

            if label and not summary_node and self._current_leaf_id is not None:
                self.append_entry(
                    entry_type=SessionEntryType.LABEL,
                    content=label,
                    parent_id=self._current_leaf_id,
                )

            return NavigateTreeResult(
                target_id=target_id,
                old_leaf_id=old_leaf,
                new_leaf_id=self._current_leaf_id,
                editor_text=editor_text,
                common_ancestor_id=lca_id,
                abandoned_entries_count=len(abandoned),
                summary_entry=summary_node,
                is_noop=False,
            )

    def get_tree(self) -> list[SessionTreeNode]:
        """Project flat entries into hierarchical forest of SessionTreeNodes."""
        with self._lock:
            nodes_by_id: dict[str, SessionTreeNode] = {
                e.entry_id: SessionTreeNode(entry=e) for e in self._entries
            }
            roots: list[SessionTreeNode] = []

            for entry in self._entries:
                node = nodes_by_id[entry.entry_id]
                if entry.parent_id is None or entry.parent_id not in nodes_by_id:
                    roots.append(node)
                else:
                    parent_node = nodes_by_id[entry.parent_id]
                    parent_node.children.append(node)

            return roots
