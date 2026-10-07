"""[POS]: src/myrm_agent_harness/toolkits/memory/cvfs/models.py
[INPUT]: Domain primitives and data models for context virtual file system.
[OUTPUT]: Strongly typed contracts for VFS nodes, read results, and hierarchical tree responses.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class VFSNamespaceKind(StrEnum):
    """Canonical top-level namespaces in Context Virtual File System."""

    MEMORIES = "memories"
    SKILLS = "skills"
    RESOURCES = "resources"
    USER = "user"
    ARTIFACTS = "artifacts"


class VFSNodeType(StrEnum):
    """Node classification in Context Virtual File System."""

    DIRECTORY = "directory"
    FILE = "file"


class VFSNodeInfo(BaseModel):
    """Metadata descriptor for a virtual file system node."""

    uri: str = Field(..., description="Canonical ctx:// or context:// URI")
    parent_uri: str = Field(..., description="Parent directory URI")
    name: str = Field(..., description="Node name or file basename")
    node_type: VFSNodeType = Field(..., description="Node type: directory or file")
    size_bytes: int = Field(default=0, ge=0, description="Payload byte size")
    metadata: dict[str, str] = Field(default_factory=dict, description="Contextual tags and annotations")
    created_at_epoch: float = Field(..., description="Creation epoch timestamp in seconds")
    updated_at_epoch: float = Field(..., description="Last update epoch timestamp in seconds")


class VFSReadResult(BaseModel):
    """Deterministic read result containing sliced content and pagination info."""

    uri: str = Field(..., description="Canonical URI of read file")
    content: str = Field(..., description="Sliced text payload")
    size_bytes: int = Field(..., description="Total size in bytes")
    offset: int = Field(default=0, ge=0, description="Read offset position")
    limit: int = Field(default=4000, ge=1, description="Read byte limit")
    has_more: bool = Field(default=False, description="Whether more content is available beyond limit")


class VFSTreeNode(BaseModel):
    """Recursive tree structure node for hierarchy rendering."""

    name: str = Field(..., description="Directory or file name")
    uri: str = Field(..., description="Full canonical URI")
    node_type: VFSNodeType = Field(..., description="Node type")
    children: list["VFSTreeNode"] = Field(default_factory=list, description="Child nodes")


class VFSTreeResult(BaseModel):
    """Formatted ASCII tree and structural summary of context exploration."""

    root_uri: str = Field(..., description="Exploration root URI")
    total_nodes: int = Field(default=0, ge=0, description="Total node count traversed")
    rendered_tree: str = Field(..., description="Visual ASCII tree representation")


class VFSSubtreeStats(BaseModel):
    """Aggregated volume and structural statistics for a VFS subtree."""

    root_uri: str = Field(..., description="Target subtree root URI")
    total_nodes: int = Field(default=0, ge=0, description="Total node count in subtree")
    file_count: int = Field(default=0, ge=0, description="Total file count in subtree")
    directory_count: int = Field(default=0, ge=0, description="Total directory count in subtree")
    total_bytes: int = Field(default=0, ge=0, description="Total storage bytes across files")


class VFSMountInfo(BaseModel):
    """Descriptor for dynamically mounted context providers."""

    mount_point: str = Field(..., description="Target mount point URI")
    description: str = Field(default="", description="Mount description")
    is_read_only: bool = Field(default=True, description="Whether mount is strictly read-only")
    mounted_at_epoch: float = Field(..., description="Timestamp of mounting")

