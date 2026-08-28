"""Directory Tree DAG Builder for Job Lane bottom-up summarization.

Constructs an in-memory directory DAG as files are discovered. When finalize() is called,
it resolves leaf directories (those with no subdirectories or already satisfied dependencies)
and provides a topological bottom-up reduce order so directory summaries fold upward
without waiting for Object Lane vector embeddings.

[INPUT]
- types.py::DirNode (POS: Node representation in the directory DAG)

[OUTPUT]
- DirTreeBuilder: In-memory directory DAG builder and topological folder
- ancestor_dirs: Helper to decompose POSIX paths into directory hierarchies
- dir_depth: Helper to calculate folder hierarchy depth

[POS]
Job Lane DAG coordination engine for toolkits.retriever.ingest.
"""

from __future__ import annotations

import posixpath
from collections.abc import Callable
from typing import Awaitable

from myrm_agent_harness.toolkits.retriever.ingest.types import DirNode


def ancestor_dirs(relpath: str) -> list[str]:
    """Return all ancestor directory URIs of an object URI from root '/' upward.

    Example:
        'src/components/button.tsx' -> ['/', '/src', '/src/components']
    """
    clean_path = relpath.strip().replace("\\", "/")
    if not clean_path.startswith("/"):
        clean_path = f"/{clean_path}"
    parts = [p for p in clean_path.split("/") if p]
    if not parts:
        return ["/"]

    dirs = ["/"]
    cur = ""
    for seg in parts[:-1]:  # Exclude the leaf filename itself
        cur = f"{cur}/{seg}"
        dirs.append(cur)
    return dirs


def dir_depth(path: str) -> int:
    """Calculate directory depth based on path segment count.

    Example:
        '/' -> 0, '/src' -> 1, '/src/components' -> 2
    """
    clean_path = path.strip().replace("\\", "/")
    parts = [p for p in clean_path.split("/") if p]
    return len(parts)


class DirTreeBuilder:
    """Per-run in-memory directory tree DAG builder for Job Lane."""

    def __init__(self) -> None:
        self._nodes: dict[str, DirNode] = {
            "/": DirNode(path="/", parent_path=None, depth=0)
        }
        self._is_finalized: bool = False

    def add_object(self, relpath: str) -> None:
        """Register a discovered file and automatically construct its ancestor directories."""
        if self._is_finalized:
            raise RuntimeError("Cannot add objects after DirTreeBuilder is finalized.")

        clean_path = relpath.strip().replace("\\", "/")
        if not clean_path.startswith("/"):
            clean_path = f"/{clean_path}"

        ancestors = ancestor_dirs(clean_path)
        for i, d_path in enumerate(ancestors):
            if d_path not in self._nodes:
                parent = ancestors[i - 1] if i > 0 else None
                depth = dir_depth(d_path)
                self._nodes[d_path] = DirNode(path=d_path, parent_path=parent, depth=depth)
                if parent and parent in self._nodes:
                    if d_path not in self._nodes[parent].children_dirs:
                        self._nodes[parent].children_dirs.append(d_path)

        leaf_dir = ancestors[-1]
        if clean_path not in self._nodes[leaf_dir].children_files:
            self._nodes[leaf_dir].children_files.append(clean_path)

    def finalize(self) -> list[str]:
        """Finalize the tree and return initial leaf directory paths ready for summarization."""
        self._is_finalized = True
        ready_dirs: list[str] = []

        for node in self._nodes.values():
            node.pending_children_count = len(node.children_dirs)
            if node.pending_children_count == 0:
                ready_dirs.append(node.path)

        # Sort deepest directories first
        ready_dirs.sort(key=lambda p: self._nodes[p].depth, reverse=True)
        return ready_dirs

    def on_directory_summarized(self, dir_path: str, summary_text: str) -> str | None:
        """Record directory summary completion and return parent path if parent is now ready."""
        if dir_path not in self._nodes:
            return None

        node = self._nodes[dir_path]
        node.is_summarized = True
        node.summary_text = summary_text

        parent_path = node.parent_path
        if parent_path and parent_path in self._nodes:
            parent_node = self._nodes[parent_path]
            parent_node.pending_children_count -= 1
            if parent_node.pending_children_count <= 0 and not parent_node.is_summarized:
                return parent_path

        return None

    def get_node(self, dir_path: str) -> DirNode | None:
        """Retrieve node information for a given path."""
        return self._nodes.get(dir_path)

    @property
    def all_nodes(self) -> dict[str, DirNode]:
        """Read-only view of all registered nodes in the DAG."""
        return self._nodes
