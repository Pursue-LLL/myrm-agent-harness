"""[POS]: src/myrm_agent_harness/toolkits/memory/cvfs/vfs.py
[INPUT]: Normalized ctx:// URIs, text contents, and tree depth parameters.
[OUTPUT]: ContextVirtualFileSystem facade providing ls, tree, read, write, and find operations.
"""

import time
from pathlib import Path

from .models import VFSNodeInfo, VFSNodeType, VFSReadResult, VFSTreeResult
from .protocol import CVFSProtocol, CVFSProtocolError
from .store import CVFSRegistryStore


class ContextVirtualFileSystem:
    """Unified Context Virtual File System delivering deterministic exploration and asset access."""

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self.store = CVFSRegistryStore(db_path=db_path)
        self._ensure_root_nodes()

    def _ensure_root_nodes(self) -> None:
        """Initialize standard root and namespace container directories."""
        now = time.time()
        root_info = VFSNodeInfo(
            uri="ctx://",
            parent_uri="",
            name="root",
            node_type=VFSNodeType.DIRECTORY,
            size_bytes=0,
            metadata={"description": "Root namespace of Context Virtual File System"},
            created_at_epoch=now,
            updated_at_epoch=now,
        )
        self.store.put_node(root_info)

        # Standard top-level namespaces
        for ns in ("resources", "user", "artifacts"):
            ns_uri = f"ctx://{ns}"
            ns_info = VFSNodeInfo(
                uri=ns_uri,
                parent_uri="ctx://",
                name=ns,
                node_type=VFSNodeType.DIRECTORY,
                size_bytes=0,
                metadata={"namespace": ns},
                created_at_epoch=now,
                updated_at_epoch=now,
            )
            self.store.put_node(ns_info)

    def mkdir(self, uri: str, metadata: dict[str, str] | None = None) -> VFSNodeInfo:
        """Create virtual directory, recursively ensuring parents exist."""
        norm_uri = CVFSProtocol.normalize_uri(uri)
        if norm_uri == "ctx://":
            node, _ = self.store.get_node("ctx://") or (None, "")
            if node:
                return node

        CVFSProtocol.validate_namespace(norm_uri)
        parent_uri = CVFSProtocol.get_parent_uri(norm_uri)
        name = CVFSProtocol.get_basename(norm_uri)

        # Recursively ensure parent exists if not root
        if parent_uri and parent_uri != "ctx://":
            self.mkdir(parent_uri)

        now = time.time()
        node = VFSNodeInfo(
            uri=norm_uri,
            parent_uri=parent_uri,
            name=name,
            node_type=VFSNodeType.DIRECTORY,
            size_bytes=0,
            metadata=metadata or {},
            created_at_epoch=now,
            updated_at_epoch=now,
        )
        self.store.put_node(node)
        return node

    def write(
        self,
        uri: str,
        content: str,
        metadata: dict[str, str] | None = None,
    ) -> VFSNodeInfo:
        """Write text payload into a virtual file, creating parent directories automatically."""
        norm_uri = CVFSProtocol.normalize_uri(uri)
        if norm_uri == "ctx://":
            raise CVFSProtocolError("Cannot write file content to root URI 'ctx://'")

        CVFSProtocol.validate_namespace(norm_uri)
        parent_uri = CVFSProtocol.get_parent_uri(norm_uri)
        name = CVFSProtocol.get_basename(norm_uri)

        # Ensure parent directory hierarchy exists
        self.mkdir(parent_uri)

        now = time.time()
        size_bytes = len(content.encode("utf-8"))
        node = VFSNodeInfo(
            uri=norm_uri,
            parent_uri=parent_uri,
            name=name,
            node_type=VFSNodeType.FILE,
            size_bytes=size_bytes,
            metadata=metadata or {},
            created_at_epoch=now,
            updated_at_epoch=now,
        )
        self.store.put_node(node, content=content)
        return node

    def read(self, uri: str, offset: int = 0, limit: int = 4000) -> VFSReadResult:
        """Deterministically read content snippet from virtual file."""
        norm_uri = CVFSProtocol.normalize_uri(uri)
        res = self.store.get_node(norm_uri)
        if not res:
            raise FileNotFoundError(f"VFS file not found: {uri}")

        node, content = res
        if node.node_type != VFSNodeType.FILE:
            raise IsADirectoryError(f"Target URI '{uri}' is a directory, not a readable file")

        total_bytes = len(content.encode("utf-8"))
        sliced = content[offset: offset + limit]
        has_more = (offset + limit) < len(content)

        return VFSReadResult(
            uri=norm_uri,
            content=sliced,
            size_bytes=total_bytes,
            offset=offset,
            limit=limit,
            has_more=has_more,
        )

    def ls(self, uri: str = "ctx://") -> list[VFSNodeInfo]:
        """List direct child nodes under specified virtual directory."""
        norm_uri = CVFSProtocol.normalize_uri(uri)
        return self.store.list_children(parent_uri=norm_uri)

    def delete(self, uri: str) -> bool:
        """Delete target node and its sub-nodes recursively."""
        norm_uri = CVFSProtocol.normalize_uri(uri)
        if norm_uri == "ctx://":
            raise CVFSProtocolError("Root directory 'ctx://' cannot be deleted")
        return self.store.delete_node(norm_uri)

    def find(self, keyword: str, prefix_uri: str = "ctx://") -> list[VFSNodeInfo]:
        """Search nodes matching keyword in name or content."""
        norm_prefix = CVFSProtocol.normalize_uri(prefix_uri)
        return self.store.find_nodes(keyword=keyword, prefix_uri=norm_prefix)

    def tree(self, uri: str = "ctx://", max_depth: int = 3) -> VFSTreeResult:
        """Render visual POSIX ASCII tree representation of the virtual filesystem hierarchy."""
        norm_root = CVFSProtocol.normalize_uri(uri)
        total_counter = [0]
        lines = [norm_root]

        def _traverse(current_uri: str, depth: int, prefix: str) -> None:
            if depth > max_depth:
                lines.append(f"{prefix}└── ... (max depth reached)")
                return

            children = self.store.list_children(current_uri)
            for i, child in enumerate(children):
                total_counter[0] += 1
                is_last = i == (len(children) - 1)
                connector = "└── " if is_last else "├── "
                child_prefix = "    " if is_last else "│   "

                display_name = child.name + ("/" if child.node_type == VFSNodeType.DIRECTORY else "")
                lines.append(f"{prefix}{connector}{display_name}")

                if child.node_type == VFSNodeType.DIRECTORY:
                    _traverse(child.uri, depth + 1, prefix + child_prefix)

        _traverse(norm_root, 1, "")
        rendered = "\n".join(lines)
        return VFSTreeResult(
            root_uri=norm_root,
            total_nodes=total_counter[0],
            rendered_tree=rendered,
        )

    def close(self) -> None:
        """Close registry database connection."""
        self.store.close()
