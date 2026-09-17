"""MemCube envelope contract and multi-tier metadata models.

[INPUT]
- myrm_agent_harness.toolkits.memory.types::BaseMemory (POS: Memory type system foundation)
- myrm_agent_harness.toolkits.memory.types::MemoryType (POS: Memory type system foundation)
- myrm_agent_harness.toolkits.memory.types::MemoryScope (POS: Memory type system foundation)

[OUTPUT]
- LifecycleTier: 记忆生命周期层级枚举 (L1/L2/L3/ARCHIVED)
- StoragePolicy: 物理存储介质路由策略 (RELATIONAL/VECTOR/GRAPH/EPHEMERAL)
- MemCubeHeader: 标准元数据头与 SHA256 验签指纹
- MemCubeEnvelope: 统一异构记忆泛型容器与防篡改信封契约
- wrap_into_envelope: 无损封装记忆实体为信封容器
- unwrap_envelope: 将信封容器还原为强类型记忆实体
- infer_tier_and_policy: 记忆实体的生命周期层级与存储策略自适应推导器

[POS]
统一记忆容器契约层。为异构记忆提供标准元数据头、防篡改签名与跨端传输标准。
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from myrm_agent_harness.toolkits.memory.types import (
    BaseMemory,
    ClaimMemory,
    ConversationMemory,
    EpisodicMemory,
    IntegrationMemory,
    MemoryScope,
    MemoryType,
    ProceduralMemory,
    SemanticMemory,
    TaskDigestMemory,
)


class LifecycleTier(StrEnum):
    """Hierarchical lifecycle tiers for agent memories."""

    L1_WORKBENCH = "L1_WORKBENCH"  # Active in-turn scratchpad / ephemeral working memory
    L2_CONSOLIDATED = "L2_CONSOLIDATED"  # Session consolidated rules and task digests
    L3_COMPILED = "L3_COMPILED"  # Long-term semantic vectors and graph claims
    ARCHIVED = "ARCHIVED"  # Demoted cold storage, pending garbage collection


class StoragePolicy(StrEnum):
    """Storage target backend policy for memory dispatch."""

    RELATIONAL = "relational"  # SQLite relational tables
    VECTOR = "vector"  # Vector database (Qdrant / Milvus)
    GRAPH = "graph"  # Graph database / claim nodes
    EPHEMERAL = "ephemeral"  # In-memory only (e.g. LocalWorkingMemoryBlock)


class MemCubeHeader(BaseModel):
    """Canonical metadata header for all MemCube items."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    cube_id: str = Field(default_factory=lambda: f"cube_{uuid4().hex[:12]}")
    memory_type: MemoryType
    lifecycle_tier: LifecycleTier = LifecycleTier.L2_CONSOLIDATED
    storage_policy: StoragePolicy = StoragePolicy.RELATIONAL
    source: str = Field(default="agent_self", description="Origin source (e.g. session_id, skill_id)")
    scope: MemoryScope = Field(default_factory=MemoryScope)
    is_user_protected: bool = Field(default=False, description="Immune to automatic eviction")
    usage_count: int = Field(default=0, ge=0)
    priority: int = Field(default=2, ge=0, le=5)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_accessed_at: datetime | None = Field(default=None, description="Last access timestamp")
    audit_hash: str | None = Field(default=None, description="SHA256 fingerprint for tamper proofing")


class MemCubeEnvelope[T](BaseModel):
    """Standardized serialization envelope for cross-tier and cross-platform transport."""

    model_config = ConfigDict(extra="ignore")

    header: MemCubeHeader
    payload: T

    def compute_audit_hash(self) -> str:
        """Calculate canonical SHA256 hash over header (excluding hash) and payload."""
        header_dict = self.header.model_dump(mode="json", exclude={"audit_hash"})
        payload_data: object
        if hasattr(self.payload, "model_dump"):
            payload_data = self.payload.model_dump(mode="json")
        else:
            payload_data = self.payload

        canonical_repr = json.dumps(
            {"header": header_dict, "payload": payload_data},
            sort_keys=True,
            ensure_ascii=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(canonical_repr.encode("utf-8")).hexdigest()

    def seal(self) -> MemCubeEnvelope[T]:
        """Compute and set audit_hash in header."""
        self.header.audit_hash = self.compute_audit_hash()
        return self

    def verify_audit_hash(self) -> bool:
        """Verify that the payload matches the sealed audit_hash."""
        if not self.header.audit_hash:
            return False
        return self.compute_audit_hash() == self.header.audit_hash


def infer_tier_and_policy(memory: BaseMemory) -> tuple[LifecycleTier, StoragePolicy]:
    """Derive appropriate tier and storage policy from memory type."""
    if isinstance(memory, TaskDigestMemory):
        return LifecycleTier.L2_CONSOLIDATED, StoragePolicy.RELATIONAL
    if isinstance(memory, ProceduralMemory):
        return LifecycleTier.L2_CONSOLIDATED, StoragePolicy.RELATIONAL
    if isinstance(memory, (SemanticMemory, EpisodicMemory, IntegrationMemory)):
        return LifecycleTier.L3_COMPILED, StoragePolicy.VECTOR
    if isinstance(memory, ClaimMemory):
        return LifecycleTier.L3_COMPILED, StoragePolicy.GRAPH
    if isinstance(memory, ConversationMemory):
        return LifecycleTier.L1_WORKBENCH, StoragePolicy.RELATIONAL
    return LifecycleTier.L2_CONSOLIDATED, StoragePolicy.RELATIONAL


def wrap_into_envelope(
    memory: BaseMemory,
    tier: LifecycleTier | None = None,
    policy: StoragePolicy | None = None,
    seal_immediately: bool = True,
) -> MemCubeEnvelope[dict[str, object]]:
    """Convert an in-memory entity into a portable MemCubeEnvelope."""
    default_tier, default_policy = infer_tier_and_policy(memory)
    resolved_tier = tier or default_tier
    resolved_policy = policy or default_policy

    header = MemCubeHeader(
        cube_id=f"cube_{memory.id}",
        memory_type=memory.memory_type,
        lifecycle_tier=resolved_tier,
        storage_policy=resolved_policy,
        source=getattr(memory, "source", "agent_self") or "agent_self",
        scope=memory.scope,
        is_user_protected=getattr(memory, "is_user_protected", False),
        usage_count=int(getattr(memory, "access_count", getattr(memory, "usage_count", 0)) or 0),
        priority=getattr(memory, "priority", 2),
        created_at=memory.created_at,
        updated_at=memory.updated_at,
        last_accessed_at=getattr(memory, "last_accessed_at", None),
    )

    payload_dict = memory.model_dump(mode="json")
    envelope = MemCubeEnvelope[dict[str, object]](header=header, payload=payload_dict)
    if seal_immediately:
        envelope.seal()
    return envelope


_TYPE_MODEL_MAP: dict[str, type[BaseMemory]] = {
    MemoryType.SEMANTIC.value: SemanticMemory,
    MemoryType.EPISODIC.value: EpisodicMemory,
    MemoryType.PROCEDURAL.value: ProceduralMemory,
    MemoryType.CONVERSATION.value: ConversationMemory,
    MemoryType.CLAIM.value: ClaimMemory,
    MemoryType.INTEGRATION.value: IntegrationMemory,
    MemoryType.TASK_DIGEST.value: TaskDigestMemory,
}


def unwrap_envelope(envelope: MemCubeEnvelope[dict[str, object]]) -> BaseMemory:
    """Restore concrete BaseMemory derivative from an envelope payload."""
    mem_type_val = envelope.header.memory_type.value if hasattr(envelope.header.memory_type, "value") else str(envelope.header.memory_type)
    model_cls = _TYPE_MODEL_MAP.get(mem_type_val)
    if model_cls is None:
        raise ValueError(f"Unsupported memory type in envelope: {mem_type_val}")

    entity = model_cls.model_validate(envelope.payload)
    if hasattr(entity, "access_count") and envelope.header.usage_count > 0:
        entity.access_count = envelope.header.usage_count
    if hasattr(entity, "last_accessed_at") and envelope.header.last_accessed_at is not None:
        entity.last_accessed_at = envelope.header.last_accessed_at
    return entity
