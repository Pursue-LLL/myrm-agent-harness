"""Append-only immutable conversation tree storage.

Provides parentId topological storage, ancestor chain projection,
Lowest Common Ancestor (LCA) resolution, and branch divergence extraction
for non-destructive navigation.

[INPUT]
- runtime.context.tree_session_storage_types::TreeEntry (POS: Immutable tree-structured session types and
  navigation models.)

[OUTPUT]
- TreeSessionStorage: Storage for an append-only, immutable conversation tree.

[POS]
Append-only immutable conversation tree storage.
"""

from __future__ import annotations

from collections.abc import Sequence

from .tree_session_storage_types import TreeEntry


class TreeSessionStorage:
    """Storage for an append-only, immutable conversation tree."""

    def __init__(self) -> None:
        self._entries: dict[str, TreeEntry] = {}
        self._children_index: dict[str, list[str]] = {}
        self._root_ids: list[str] = []

    def append_entry(self, entry: TreeEntry) -> TreeEntry:
        """Atomically append an immutable entry to the tree.

        Raises:
            KeyError: If entry_id already exists (append-only violation).
            ValueError: If parent_id is specified but does not exist in the tree.
        """
        if entry.entry_id in self._entries:
            raise KeyError(f"Entry '{entry.entry_id}' already exists. Conversation tree is strictly append-only.")

        if entry.parent_id is not None:
            if entry.parent_id not in self._entries:
                raise ValueError(
                    f"Parent entry '{entry.parent_id}' does not exist in tree for new entry '{entry.entry_id}'."
                )
            self._children_index.setdefault(entry.parent_id, []).append(entry.entry_id)
        else:
            self._root_ids.append(entry.entry_id)

        self._entries[entry.entry_id] = entry
        return entry

    def get_entry(self, entry_id: str) -> TreeEntry | None:
        """Retrieve an entry by ID, or None if not found."""
        return self._entries.get(entry_id)

    def get_children(self, entry_id: str) -> list[TreeEntry]:
        """Return all direct child entries of the given entry."""
        child_ids = self._children_index.get(entry_id, [])
        return [self._entries[cid] for cid in child_ids if cid in self._entries]

    def get_roots(self) -> list[TreeEntry]:
        """Return all root entries."""
        return [self._entries[rid] for rid in self._root_ids if rid in self._entries]

    def total_entries_count(self) -> int:
        """Return total count of immutable entries recorded."""
        return len(self._entries)

    def get_ancestor_path(self, leaf_id: str) -> list[TreeEntry]:
        """Trace the ancestry chain from root to the specified leaf entry.

        Returns:
            An ordered list starting at the root and terminating at leaf_id.
        Raises:
            KeyError: If leaf_id is not found in the storage.
        """
        if leaf_id not in self._entries:
            raise KeyError(f"Leaf entry '{leaf_id}' not found in tree storage.")

        path: list[TreeEntry] = []
        curr_id: str | None = leaf_id
        visited: set[str] = set()

        while curr_id is not None:
            if curr_id in visited:
                raise ValueError(f"Cycle detected at entry '{curr_id}'.")
            visited.add(curr_id)

            entry = self._entries.get(curr_id)
            if entry is None:
                break
            path.append(entry)
            curr_id = entry.parent_id

        path.reverse()
        return path

    def find_lca(self, entry_a_id: str, entry_b_id: str) -> TreeEntry | None:
        """Compute the Lowest Common Ancestor (LCA) between two entries.

        Returns:
            The deepest common ancestor TreeEntry, or None if they belong to disjoint roots.
        """
        if entry_a_id not in self._entries or entry_b_id not in self._entries:
            return None

        # Collect ancestry sets of A
        ancestors_a: set[str] = set()
        curr_id: str | None = entry_a_id
        while curr_id is not None:
            ancestors_a.add(curr_id)
            entry = self._entries.get(curr_id)
            curr_id = entry.parent_id if entry else None

        # Trace ancestry of B from bottom up to find first node present in A's ancestry
        curr_id = entry_b_id
        while curr_id is not None:
            if curr_id in ancestors_a:
                return self._entries.get(curr_id)
            entry = self._entries.get(curr_id)
            curr_id = entry.parent_id if entry else None

        return None

    def get_branch_divergence(
        self,
        source_leaf_id: str,
        target_entry_id: str,
    ) -> Sequence[TreeEntry]:
        """Extract entries on the source branch that diverge from the target.

        Specifically, finds LCA(source_leaf, target_entry) and returns all entries
        strictly descending from LCA down to source_leaf_id.
        """
        lca = self.find_lca(source_leaf_id, target_entry_id)
        if lca is None:
            # If no common ancestor, the entire source ancestry is divergent
            return self.get_ancestor_path(source_leaf_id)

        source_path = self.get_ancestor_path(source_leaf_id)
        lca_index = -1
        for idx, entry in enumerate(source_path):
            if entry.entry_id == lca.entry_id:
                lca_index = idx
                break

        if lca_index == -1 or lca_index + 1 >= len(source_path):
            return []

        return source_path[lca_index + 1 :]
