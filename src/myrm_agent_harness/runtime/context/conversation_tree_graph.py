"""In-session tree-structured conversation graph and branch navigation engine.

Provides DAG-based branching, in-place node checkout/replay, multi-dimensional
message filtering, and bookmark management inspired by Pi Agent Tree History.

[INPUT]
- runtime.context.conversation_tree_types::BranchPathInfo, ConversationTreeNode, TreeBookmark,
  TreeFilterCriteria, TreeNodeKind (POS: Type definitions for tree-structured conversation graph and branch
  replay engine.)

[OUTPUT]
- ConversationTreeGraph: Manages an in-session DAG conversation tree with branching and projection.

[POS]
In-session tree-structured conversation graph and branch navigation engine.
"""

import time
import uuid

from myrm_agent_harness.runtime.context.conversation_tree_types import (
    BranchPathInfo,
    ConversationTreeNode,
    TreeBookmark,
    TreeFilterCriteria,
    TreeNodeKind,
)


class ConversationTreeGraph:
    """Manages an in-session DAG conversation tree with branching and projection."""

    def __init__(self) -> None:
        self._nodes: dict[str, ConversationTreeNode] = {}
        self._root_id: str | None = None
        self._current_leaf_id: str | None = None
        self._bookmarks: dict[str, TreeBookmark] = {}

    @property
    def root_id(self) -> str | None:
        """Return the root node ID of the tree."""
        return self._root_id

    @property
    def current_leaf_id(self) -> str | None:
        """Return the currently active leaf/node pointer (HEAD)."""
        return self._current_leaf_id

    def add_node(
        self,
        kind: TreeNodeKind,
        role: str,
        content: str,
        parent_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> ConversationTreeNode:
        """Append a new node to the tree branching from parent_id or current leaf."""
        now = time.time()
        node_id = f"node-{uuid.uuid4().hex[:10]}"
        pid = parent_id if parent_id is not None else self._current_leaf_id

        # Validate parent exists if specified
        if pid is not None and pid not in self._nodes:
            raise ValueError(f"Parent node `{pid}` does not exist in graph.")

        new_node = ConversationTreeNode(
            node_id=node_id,
            parent_id=pid,
            children_ids=[],
            kind=kind,
            role=role,
            content=content,
            timestamp=now,
            metadata=metadata or {},
        )

        self._nodes[node_id] = new_node

        # Update parent's children list
        if pid is not None:
            parent_node = self._nodes[pid]
            updated_children = list(parent_node.children_ids)
            updated_children.append(node_id)
            self._nodes[pid] = ConversationTreeNode(
                node_id=parent_node.node_id,
                parent_id=parent_node.parent_id,
                children_ids=updated_children,
                kind=parent_node.kind,
                role=parent_node.role,
                content=parent_node.content,
                timestamp=parent_node.timestamp,
                metadata=parent_node.metadata,
                is_bookmarked=parent_node.is_bookmarked,
                bookmark_note=parent_node.bookmark_note,
            )
        else:
            if self._root_id is None:
                self._root_id = node_id

        self._current_leaf_id = node_id
        return new_node

    def switch_active_node(self, node_id: str) -> list[ConversationTreeNode]:
        """Switch active pointer (HEAD checkout) and return the projected branch."""
        if node_id not in self._nodes:
            raise KeyError(f"Node `{node_id}` not found in graph.")

        self._current_leaf_id = node_id
        return self.project_branch(node_id)

    def project_branch(
        self, target_node_id: str | None = None
    ) -> list[ConversationTreeNode]:
        """Trace from target node up to root and return chronological message chain."""
        start_id = target_node_id or self._current_leaf_id
        if not start_id or start_id not in self._nodes:
            return []

        chain: list[ConversationTreeNode] = []
        curr: str | None = start_id
        while curr is not None:
            node = self._nodes.get(curr)
            if not node:
                break
            chain.append(node)
            curr = node.parent_id

        chain.reverse()
        return chain

    def list_all_branches(self) -> list[BranchPathInfo]:
        """Find all leaf nodes in the DAG and compile summary for each branch."""
        leaf_nodes = [
            n for n in self._nodes.values() if len(n.children_ids) == 0
        ]
        branches: list[BranchPathInfo] = []

        for leaf in leaf_nodes:
            path = self.project_branch(leaf.node_id)
            root_to_leaf = [p.node_id for p in path]
            branch_title = (
                f"Branch-{leaf.node_id[:8]} ({path[0].role} -> {leaf.role})"
                if path
                else "Empty Branch"
            )
            preview = leaf.content[:80] if leaf.content else "[Empty]"
            branches.append(
                BranchPathInfo(
                    leaf_id=leaf.node_id,
                    path_length=len(path),
                    root_to_leaf_ids=root_to_leaf,
                    branch_name=branch_title,
                    leaf_preview=preview,
                )
            )

        return branches

    def toggle_bookmark(
        self, node_id: str, is_bookmarked: bool = True, note: str = ""
    ) -> bool:
        """Add or remove an architectural/decision bookmark on a node."""
        node = self._nodes.get(node_id)
        if not node:
            return False

        updated = ConversationTreeNode(
            node_id=node.node_id,
            parent_id=node.parent_id,
            children_ids=node.children_ids,
            kind=node.kind,
            role=node.role,
            content=node.content,
            timestamp=node.timestamp,
            metadata=node.metadata,
            is_bookmarked=is_bookmarked,
            bookmark_note=note if is_bookmarked else "",
        )
        self._nodes[node_id] = updated

        if is_bookmarked:
            self._bookmarks[node_id] = TreeBookmark(
                node_id=node_id,
                title=node.content[:60],
                note=note,
                created_at=time.time(),
            )
        else:
            self._bookmarks.pop(node_id, None)

        return True

    def list_bookmarks(self) -> list[TreeBookmark]:
        """Return all bookmarked decisions in the graph."""
        return list(self._bookmarks.values())

    def filter_branch_messages(
        self,
        nodes: list[ConversationTreeNode],
        criteria: TreeFilterCriteria,
    ) -> list[ConversationTreeNode]:
        """Filter a projected node chain by criteria (role, timestamp, bookmark)."""
        filtered: list[ConversationTreeNode] = []
        for n in nodes:
            if criteria.include_kinds and n.kind not in criteria.include_kinds:
                continue
            if (
                criteria.min_timestamp is not None
                and n.timestamp < criteria.min_timestamp
            ):
                continue
            if criteria.only_bookmarked and not n.is_bookmarked:
                continue
            filtered.append(n)
        return filtered

    def get_node(self, node_id: str) -> ConversationTreeNode | None:
        """Retrieve node by ID."""
        return self._nodes.get(node_id)

    def total_nodes(self) -> int:
        """Return total nodes count in the tree."""
        return len(self._nodes)
