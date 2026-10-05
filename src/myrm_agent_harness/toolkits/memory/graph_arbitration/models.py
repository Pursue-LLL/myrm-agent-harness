from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class FactStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    CONFLICTING = "conflicting"
    ARCHIVED = "archived"


class ConflictResolutionAction(StrEnum):
    SUPERSEDE_OLD = "supersede_old"
    REINFORCE_EXISTING = "reinforce_existing"
    COEXIST = "coexist"


class EntityNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    entity_type: str = "general"
    description: str = ""
    created_at_epoch_s: float
    last_accessed_epoch_s: float


class EntityRelationEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge_id: str
    source_node_id: str
    target_node_id: str
    predicate: str
    fact_value: str
    base_weight: float = 1.0
    dynamic_weight: float = 1.0
    status: FactStatus = FactStatus.ACTIVE
    created_at_epoch_s: float
    last_verified_epoch_s: float
    access_count: int = 1
    causal_superseded_by: str | None = None
    properties: dict[str, str | int | float | bool] = Field(default_factory=dict)


class ArbitrationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ConflictResolutionAction
    active_edge_id: str
    superseded_edge_ids: list[str] = Field(default_factory=list)
    explanation: str
    confidence: float = 1.0
