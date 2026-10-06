"""Git-like non-linear session tree and parent-id branching engine."""

from __future__ import annotations

import json
import time
import uuid
from threading import RLock

from myrm_agent_harness.runtime.context.git_session_tree_types import (
    GitSessionBranchDescriptor,
    GitSessionTreeNode,
    SessionTreeEntryKind,
    SessionTreeTopology,
)


class GitLikeSessionTreeEngine:
    """Manages an append-only non-linear tree of conversation turns supporting branching and rewind."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._nodes: dict[str, GitSessionTreeNode] = {}
        self._branches: dict[str, GitSessionBranchDescriptor] = {}
        self._root_node_id: str | None = None
        self._active_head_id: str | None = None
        self._active_branch_name: str = "main"

    @property
    def root_node_id(self) -> str | None:
        with self._lock:
            return self._root_node_id

    @property
    def active_head_id(self) -> str | None:
        with self._lock:
            return self._active_head_id

    @property
    def active_branch_name(self) -> str:
        with self._lock:
            return self._active_branch_name

    def append_entry(
        self,
        content: str,
        role: str = "user",
        entry_kind: SessionTreeEntryKind = SessionTreeEntryKind.MESSAGE,
        parent_id: str | None = None,
        metadata: dict[str, str] | None = None,
        current_time: float | None = None,
    ) -> GitSessionTreeNode:
        """Appends a new immutable node to the session tree under active head or specified parent."""
        now = time.time() if current_time is None else current_time
        node_id = f"node-{uuid.uuid4().hex[:12]}"

        with self._lock:
            actual_parent = parent_id if parent_id is not None else self._active_head_id

            if actual_parent is not None and actual_parent not in self._nodes:
                raise ValueError(f"Parent node '{actual_parent}' does not exist in session tree.")

            node = GitSessionTreeNode(
                node_id=node_id,
                parent_id=actual_parent,
                entry_kind=entry_kind,
                role=role,
                content=content,
                created_at=now,
                metadata=metadata or {},
            )
            self._nodes[node_id] = node

            if self._root_node_id is None:
                self._root_node_id = node_id
                # Initialize default main branch
                self._branches["main"] = GitSessionBranchDescriptor(
                    branch_name="main",
                    fork_node_id=node_id,
                    head_node_id=node_id,
                    created_at=now,
                )

            self._active_head_id = node_id

            # Update head pointer of current branch if tracking
            if self._active_branch_name in self._branches:
                curr_br = self._branches[self._active_branch_name]
                self._branches[self._active_branch_name] = GitSessionBranchDescriptor(
                    branch_name=curr_br.branch_name,
                    fork_node_id=curr_br.fork_node_id,
                    head_node_id=node_id,
                    created_at=curr_br.created_at,
                )

            return node

    def branch(
        self,
        source_node_id: str,
        branch_name: str,
        current_time: float | None = None,
    ) -> GitSessionBranchDescriptor:
        """Forks a new named exploration branch from any historical node without modifying main line."""
        now = time.time() if current_time is None else current_time
        clean_name = branch_name.strip()
        if not clean_name:
            raise ValueError("Branch name cannot be empty.")

        with self._lock:
            if source_node_id not in self._nodes:
                raise ValueError(f"Source fork node '{source_node_id}' does not exist.")
            if clean_name in self._branches:
                raise ValueError(f"Branch '{clean_name}' already exists.")

            desc = GitSessionBranchDescriptor(
                branch_name=clean_name,
                fork_node_id=source_node_id,
                head_node_id=source_node_id,
                created_at=now,
            )
            self._branches[clean_name] = desc
            self._active_head_id = source_node_id
            self._active_branch_name = clean_name
            return desc

    def checkout(self, target: str) -> GitSessionTreeNode:
        """Switches active cursor to another branch head or specific node id."""
        with self._lock:
            # Check if target is branch name
            if target in self._branches:
                desc = self._branches[target]
                self._active_head_id = desc.head_node_id
                self._active_branch_name = target
                return self._nodes[desc.head_node_id]

            # Check if target is node id
            if target in self._nodes:
                self._active_head_id = target
                return self._nodes[target]

            raise ValueError(f"Target '{target}' is neither a known branch name nor a valid node ID.")

    def rewind(self, steps: int = 1) -> GitSessionTreeNode:
        """Rewinds cursor N steps backwards along parent chain while fully preserving child nodes."""
        if steps < 1:
            raise ValueError("Rewind steps must be at least 1.")

        with self._lock:
            if self._active_head_id is None:
                raise ValueError("Cannot rewind an empty session tree.")

            curr = self._nodes[self._active_head_id]
            for _ in range(steps):
                if curr.parent_id is None:
                    break
                curr = self._nodes[curr.parent_id]

            self._active_head_id = curr.node_id

            if self._active_branch_name in self._branches:
                br = self._branches[self._active_branch_name]
                self._branches[self._active_branch_name] = GitSessionBranchDescriptor(
                    branch_name=br.branch_name,
                    fork_node_id=br.fork_node_id,
                    head_node_id=curr.node_id,
                    created_at=br.created_at,
                )

            return curr

    def build_linear_context(
        self,
        from_node_id: str | None = None,
        stop_at_compaction: bool = False,
    ) -> list[GitSessionTreeNode]:
        """Traverses backwards from active or specified leaf to root, yielding topological sequence."""
        with self._lock:
            start_id = from_node_id if from_node_id is not None else self._active_head_id
            if start_id is None:
                return []

            chain: list[GitSessionTreeNode] = []
            curr_id: str | None = start_id

            while curr_id is not None:
                node = self._nodes.get(curr_id)
                if node is None:
                    break
                chain.append(node)
                if stop_at_compaction and node.entry_kind == SessionTreeEntryKind.COMPACTION_CHECKPOINT:
                    break
                curr_id = node.parent_id

            # Reverse to order from Root (earliest) to Leaf (latest)
            chain.reverse()
            return chain

    def export_topology(self) -> SessionTreeTopology:
        """Returns topological metadata summary of the session tree."""
        with self._lock:
            branch_map = {name: b.head_node_id for name, b in self._branches.items()}
            return SessionTreeTopology(
                root_node_id=self._root_node_id or "",
                active_head_id=self._active_head_id or "",
                total_nodes=len(self._nodes),
                total_branches=len(self._branches),
                branch_heads=branch_map,
            )

    def export_jsonl(self) -> str:
        """Serializes all tree nodes into standard append-only JSONL format."""
        with self._lock:
            lines: list[str] = []
            for node in self._nodes.values():
                d = {
                    "node_id": node.node_id,
                    "parent_id": node.parent_id,
                    "entry_kind": str(node.entry_kind),
                    "role": node.role,
                    "content": node.content,
                    "created_at": node.created_at,
                    "metadata": node.metadata,
                }
                lines.append(json.dumps(d, ensure_ascii=False))
            return "\n".join(lines)
