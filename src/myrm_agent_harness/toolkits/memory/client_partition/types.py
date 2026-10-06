"""Type definitions for client-isolated workspaces and memory namespace partitioning.

[INPUT]
- pydantic::{BaseModel, Field}

[OUTPUT]
- ClientPartitionConfig: Immutable configuration for client workspace and memory scoping
- ClientWorkspaceDescriptor: Resolved workspace path and isolation status
- CrossClientLeakViolation: Forensic record of detected cross-client memory leakage
- PartitionInspectionReport: Inspection summary of filtered and sanitized search results

[POS]
Data structures and value objects for client-isolated memory boundaries and workspace partitions.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class ClientPartitionConfig(BaseModel):
    """Configuration for client workspace and memory namespace partitioning."""

    client_id: str = Field(description="Unique client identifier (slug, e.g. 'acme-corp')")
    client_name: str | None = Field(default=None, description="Human-readable client display name")
    workspace_root: str = Field(
        default="workspaces/clients",
        description="Base directory for client workspace mounts",
    )
    allow_global_read: bool = Field(
        default=True,
        description="Whether this client context is allowed to read shared global memories",
    )
    strict_leak_check: bool = Field(
        default=True,
        description="Whether to raise on detected leakage or quietly filter results",
    )


class ClientWorkspaceDescriptor(BaseModel):
    """Metadata describing a resolved, isolated client workspace directory."""

    client_id: str = Field(description="Target client identifier")
    relative_path: str = Field(description="Normalized relative path from sandbox workspace root")
    absolute_path: str = Field(description="Canonical absolute path on local file system")
    is_isolated: bool = Field(default=True, description="Whether the workspace path is safely quarantined")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp when the partition descriptor was resolved",
    )


class CrossClientLeakViolation(BaseModel):
    """Forensic report entry when an out-of-boundary memory entry is detected."""

    target_client_id: str = Field(description="Active client requesting or owning the turn")
    offending_client_id: str | None = Field(
        default=None, description="Foreign client identifier attached to the memory"
    )
    offending_namespace: str = Field(description="Namespace that caused the partition violation")
    memory_id: str | None = Field(default=None, description="Identifier of the leaking memory item")
    reason: str = Field(description="Deterministic explanation of why the entry was intercepted")


class PartitionInspectionReport(BaseModel):
    """Inspection and audit result after screening retrieval results for cross-client leakage."""

    target_client_id: str = Field(description="Client identifier against which memories were screened")
    total_evaluated: int = Field(default=0, description="Total number of memory candidates evaluated")
    allowed_count: int = Field(default=0, description="Total number of memories permitted for injection")
    filtered_count: int = Field(default=0, description="Total number of memories dropped due to leakage risk")
    violations: list[CrossClientLeakViolation] = Field(
        default_factory=list, description="Detailed records of intercepted cross-client leakages"
    )
