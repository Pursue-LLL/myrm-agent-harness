"""Data models for Memory Cube Scoped Isolation & Dynamic Mounting Suite.

[INPUT]
- enum (Enum)
- pydantic (BaseModel, Field)
- datetime (datetime, UTC)

[OUTPUT]
- CubeScopeType: Classification of Memory Cube isolation boundaries.
- MemoryCube: First-class isolated memory space container.
- CubeMemoryRecord: Scoped memory item belonging to a specific cube.
- MountPolicy: Decoupled read/write dynamic mounting configuration.
- CubeQueryRequest, CubeQueryResult: Federated multi-cube recall contracts.
- CubeWriteRequest, CubeWriteResult: Authorized routed mutation contracts.

[POS]
Domain value objects and contracts for Item 124 (MemOS-aligned Memory Cube).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class CubeScopeType(StrEnum):
    """Categorical scope boundaries for Memory Cube isolation."""

    GLOBAL_SHARED = "global_shared"
    PROJECT_WORKSPACE = "project_workspace"
    AGENT_PRIVATE = "agent_private"
    EPHEMERAL_TASK = "ephemeral_task"


class MemoryCube(BaseModel):
    """First-class isolated memory space container.

    Inspired by MemOS MemCube architecture: groups memories into distinct,
    isolated compartments to eliminate cross-agent interference and noisy crosstalk.
    """

    cube_id: str = Field(..., description="Unique deterministic identifier of the cube.")
    name: str = Field(..., description="Human-readable title.")
    scope_type: CubeScopeType = Field(..., description="Scope boundary level.")
    owner_id: str | None = Field(None, description="Owner identifier (agent ID, project path, or user ID).")
    description: str = Field("", description="Purpose and contents summary.")
    is_read_only: bool = Field(False, description="When true, write operations are strictly disallowed.")
    created_at_iso: str = Field(..., description="ISO 8601 creation timestamp.")
    tags: list[str] = Field(default_factory=list, description="Categorical and domain tags.")
    item_count: int = Field(0, ge=0, description="Cached count of active memory records within this cube.")


class CubeMemoryRecord(BaseModel):
    """A scoped memory record strictly bound to a designated MemoryCube."""

    record_id: str = Field(..., description="Unique record identifier.")
    cube_id: str = Field(..., description="Target parent MemoryCube ID.")
    content: str = Field(..., description="Memory body text.")
    importance: float = Field(0.5, ge=0.0, le=1.0, description="Significance weight.")
    created_at_iso: str = Field(..., description="ISO 8601 creation timestamp.")
    metadata: dict[str, str] = Field(default_factory=dict, description="Custom domain metadata.")


class MountPolicy(BaseModel):
    """Decoupled read/write dynamic mounting topology for an agent or workflow.

    Enables multi-agent cooperation: e.g. An agent mounts [Global Preferences, Project Norms]
    as readable cubes, while strictly directing writes to its private agent cube.
    """

    agent_id: str = Field(..., description="Target agent identifier.")
    readable_cube_ids: list[str] = Field(
        default_factory=list,
        description="List of cube IDs permitted for federated retrieval.",
    )
    writable_cube_ids: list[str] = Field(
        default_factory=list,
        description="List of cube IDs permitted for mutations.",
    )
    default_write_cube_id: str | None = Field(
        None,
        description="Fallback target cube when write request does not specify one.",
    )
    strict_isolation: bool = Field(
        True,
        description="If True, any write attempt to a non-writable cube raises a hard security error.",
    )


class CubeQueryRequest(BaseModel):
    """Query payload for federated multi-cube retrieval."""

    agent_id: str | None = Field(None, description="Optional agent to resolve active mount policy.")
    explicit_cube_ids: list[str] | None = Field(
        None,
        description="Override list of target cube IDs (must be readable if agent_id is provided).",
    )
    query: str = Field(..., description="Search query or keyword.")
    limit_per_cube: int = Field(5, ge=1, le=50, description="Max records to retrieve per cube.")


class CubeQueryResult(BaseModel):
    """Federated result aggregated across authorized memory cubes."""

    query: str = Field(..., description="Executed query string.")
    records_by_cube: dict[str, list[CubeMemoryRecord]] = Field(
        default_factory=dict,
        description="Retrieved records keyed by source cube_id.",
    )
    total_found: int = Field(0, ge=0, description="Sum of records recalled across all cubes.")
    audited_cube_ids: list[str] = Field(
        default_factory=list,
        description="Cubes examined during this query.",
    )


class CubeWriteRequest(BaseModel):
    """Targeted write request to deposit memory into an authorized cube."""

    agent_id: str | None = Field(None, description="Actor agent initiating write.")
    target_cube_id: str | None = Field(
        None,
        description="Explicit target cube (defaults to agent's default_write_cube_id).",
    )
    content: str = Field(..., description="Memory body text.")
    importance: float = Field(0.5, ge=0.0, le=1.0, description="Significance weight.")
    metadata: dict[str, str] = Field(default_factory=dict, description="Custom metadata.")


class CubeWriteResult(BaseModel):
    """Outcome of routed memory persistence."""

    success: bool = Field(..., description="Whether write was authorized and committed.")
    record: CubeMemoryRecord | None = Field(None, description="Persisted record entity.")
    target_cube_id: str = Field(..., description="Target cube ID.")
    rejection_reason: str | None = Field(None, description="Diagnostic explanation if rejected.")
