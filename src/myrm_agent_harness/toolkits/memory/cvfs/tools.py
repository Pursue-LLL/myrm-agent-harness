"""[POS]: src/myrm_agent_harness/toolkits/memory/cvfs/tools.py
[INPUT]: ContextVirtualFileSystem instance and tool execution arguments.
[OUTPUT]: ContextVFSExploreTools providing agent-facing meta-tool definitions for deterministic exploration.
"""

from .models import VFSNodeInfo, VFSReadResult, VFSTreeResult
from .vfs import ContextVirtualFileSystem


class ContextVFSExploreTools:
    """Agent meta-tools exposing deterministic exploration across Context Virtual File System."""

    def __init__(self, vfs: ContextVirtualFileSystem) -> None:
        self.vfs = vfs

    def ctx_ls(self, uri: str = "ctx://") -> list[VFSNodeInfo]:
        """List immediate child nodes under target Context Virtual File System path."""
        return self.vfs.ls(uri=uri)

    def ctx_tree(self, uri: str = "ctx://", max_depth: int = 3) -> VFSTreeResult:
        """Render visual ASCII tree of context assets under target URI."""
        return self.vfs.tree(uri=uri, max_depth=max_depth)

    def ctx_read(self, uri: str, offset: int = 0, limit: int = 4000) -> VFSReadResult:
        """Deterministically read content snippet from target Context Virtual File System file."""
        return self.vfs.read(uri=uri, offset=offset, limit=limit)

    def ctx_write(
        self,
        uri: str,
        content: str,
        metadata: dict[str, str] | None = None,
    ) -> VFSNodeInfo:
        """Write or update context asset in virtual file system."""
        return self.vfs.write(uri=uri, content=content, metadata=metadata)

    def ctx_find(self, keyword: str, prefix_uri: str = "ctx://") -> list[VFSNodeInfo]:
        """Find context nodes matching keyword within target URI prefix."""
        return self.vfs.find(keyword=keyword, prefix_uri=prefix_uri)
