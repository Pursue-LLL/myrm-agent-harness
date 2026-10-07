"""[POS]: src/myrm_agent_harness/toolkits/memory/cvfs/vfs.py
[INPUT]: Normalized ctx:// URIs, text contents, and tree depth parameters.
[OUTPUT]: ContextVirtualFileSystem facade providing ls, tree, read, write, and find operations.
"""

import time
from pathlib import Path

from .models import (
    VFSMountInfo,
    VFSNodeInfo,
    VFSNodeType,
    VFSReadResult,
    VFSSubtreeStats,
    VFSTreeResult,
)
from .protocol import (
    ALLOWED_TOP_NAMESPACES,
    COMPAT_SCHEME,
    PRIMARY_SCHEME,
    CVFSProtocol,
    CVFSProtocolError,
)
from .store import CVFSRegistryStore


class ContextVirtualFileSystem:
    """Unified Context Virtual File System delivering deterministic exploration and asset access."""

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self.store = CVFSRegistryStore(db_path=db_path)
        self._mounts: dict[str, VFSMountInfo] = {}
        self._ensure_root_nodes()

    def _ensure_root_nodes(self) -> None:
        """Initialize standard root and namespace container directories across supported schemes."""
        now = time.time()
        for scheme in (COMPAT_SCHEME, PRIMARY_SCHEME):
            root_info = VFSNodeInfo(
                uri=scheme,
                parent_uri="",
                name="root",
                node_type=VFSNodeType.DIRECTORY,
                size_bytes=0,
                metadata={"description": f"Root namespace of Context Virtual File System ({scheme})"},
                created_at_epoch=now,
                updated_at_epoch=now,
            )
            self.store.put_node(root_info)

            # Standard 5 top-level namespaces
            for ns in ALLOWED_TOP_NAMESPACES:
                ns_uri = f"{scheme}{ns}"
                ns_info = VFSNodeInfo(
                    uri=ns_uri,
                    parent_uri=scheme,
                    name=ns,
                    node_type=VFSNodeType.DIRECTORY,
                    size_bytes=0,
                    metadata={"namespace": ns},
                    created_at_epoch=now,
                    updated_at_epoch=now,
                )
                self.store.put_node(ns_info)

    def _get_alternate_scheme_uri(self, uri: str) -> str | None:
        """Return URI converted to alternate scheme for seamless cross-scheme lookup."""
        if uri.startswith(PRIMARY_SCHEME):
            return COMPAT_SCHEME + uri[len(PRIMARY_SCHEME):]
        if uri.startswith(COMPAT_SCHEME):
            return PRIMARY_SCHEME + uri[len(COMPAT_SCHEME):]
        return None

    def _lookup_node(self, norm_uri: str) -> tuple[VFSNodeInfo, str] | None:
        """Look up node with fallback to alternate scheme."""
        res = self.store.get_node(norm_uri)
        if res is not None:
            return res
        alt_uri = self._get_alternate_scheme_uri(norm_uri)
        if alt_uri:
            return self.store.get_node(alt_uri)
        return None

    def mkdir(self, uri: str, metadata: dict[str, str] | None = None) -> VFSNodeInfo:
        """Create virtual directory, recursively ensuring parents exist."""
        norm_uri = CVFSProtocol.normalize_uri(uri)
        if norm_uri in (PRIMARY_SCHEME, COMPAT_SCHEME):
            res = self._lookup_node(norm_uri)
            if res:
                return res[0]

        CVFSProtocol.validate_namespace(norm_uri)
        parent_uri = CVFSProtocol.get_parent_uri(norm_uri)
        name = CVFSProtocol.get_basename(norm_uri)

        # Recursively ensure parent exists if not root
        if parent_uri and parent_uri not in (PRIMARY_SCHEME, COMPAT_SCHEME):
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
        if norm_uri in (PRIMARY_SCHEME, COMPAT_SCHEME):
            raise CVFSProtocolError(f"Cannot write file content to root URI '{norm_uri}'")

        CVFSProtocol.validate_namespace(norm_uri)
        parent_uri = CVFSProtocol.get_parent_uri(norm_uri)
        name = CVFSProtocol.get_basename(norm_uri)

        # Ensure parent directory hierarchy exists
        if parent_uri and parent_uri not in (PRIMARY_SCHEME, COMPAT_SCHEME):
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
        res = self._lookup_node(norm_uri)
        if not res:
            raise FileNotFoundError(f"VFS file not found: {uri}")

        node, content = res
        if node.node_type != VFSNodeType.FILE:
            raise IsADirectoryError(f"Target URI '{uri}' is a directory, not a readable file")

        total_bytes = len(content.encode("utf-8"))
        sliced = content[offset: offset + limit]
        has_more = (offset + limit) < len(content)

        return VFSReadResult(
            uri=node.uri,
            content=sliced,
            size_bytes=total_bytes,
            offset=offset,
            limit=limit,
            has_more=has_more,
        )

    def ls(self, uri: str = "ctx://") -> list[VFSNodeInfo]:
        """List direct child nodes under specified virtual directory."""
        norm_uri = CVFSProtocol.normalize_uri(uri)
        children = self.store.list_children(parent_uri=norm_uri)
        if not children:
            alt_uri = self._get_alternate_scheme_uri(norm_uri)
            if alt_uri:
                children = self.store.list_children(parent_uri=alt_uri)
        return children

    def delete(self, uri: str) -> bool:
        """Delete target node and its sub-nodes recursively."""
        norm_uri = CVFSProtocol.normalize_uri(uri)
        if norm_uri in (PRIMARY_SCHEME, COMPAT_SCHEME):
            raise CVFSProtocolError(f"Root directory '{norm_uri}' cannot be deleted")
        deleted = self.store.delete_node(norm_uri)
        alt_uri = self._get_alternate_scheme_uri(norm_uri)
        if alt_uri:
            self.store.delete_node(alt_uri)
        return deleted

    def find(
        self,
        keyword: str,
        prefix_uri: str = "ctx://",
        node_type: VFSNodeType | None = None,
    ) -> list[VFSNodeInfo]:
        """Search nodes matching keyword in name or content, optionally filtered by node type."""
        norm_prefix = CVFSProtocol.normalize_uri(prefix_uri)
        results = self.store.find_nodes(keyword=keyword, prefix_uri=norm_prefix, node_type=node_type)
        if not results:
            alt_uri = self._get_alternate_scheme_uri(norm_prefix)
            if alt_uri:
                results = self.store.find_nodes(keyword=keyword, prefix_uri=alt_uri, node_type=node_type)
        return results

    def stat_subtree(self, uri: str = "ctx://") -> VFSSubtreeStats:
        """Calculate aggregated node counts and storage byte size for a given URI subtree."""
        norm_uri = CVFSProtocol.normalize_uri(uri)
        stats = self.store.get_subtree_stats(norm_uri)
        if stats.total_nodes == 0:
            alt_uri = self._get_alternate_scheme_uri(norm_uri)
            if alt_uri:
                alt_stats = self.store.get_subtree_stats(alt_uri)
                if alt_stats.total_nodes > 0:
                    return alt_stats
        return stats

    def mount(
        self,
        mount_point: str,
        description: str = "",
        is_read_only: bool = True,
    ) -> VFSMountInfo:
        """Mount an external context provider at the specified virtual path."""
        norm_uri = CVFSProtocol.normalize_uri(mount_point)
        CVFSProtocol.validate_namespace(norm_uri)
        info = VFSMountInfo(
            mount_point=norm_uri,
            description=description,
            is_read_only=is_read_only,
            mounted_at_epoch=time.time(),
        )
        self._mounts[norm_uri] = info
        return info

    def list_mounts(self) -> list[VFSMountInfo]:
        """List all active mounted context providers."""
        return list(self._mounts.values())

    def tree(self, uri: str = "ctx://", max_depth: int = 3) -> VFSTreeResult:
        """Render visual POSIX ASCII tree representation of the virtual filesystem hierarchy."""
        norm_root = CVFSProtocol.normalize_uri(uri)
        total_counter = [0]
        lines = [norm_root]

        def _traverse(current_uri: str, depth: int, prefix: str) -> None:
            if depth > max_depth:
                lines.append(f"{prefix}└── ... (max depth reached)")
                return

            children = self.ls(current_uri)
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
