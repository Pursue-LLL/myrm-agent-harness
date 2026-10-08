"""Data models for prompt cache preserving ephemeral delta memory suite.

[INPUT]
pydantic::BaseModel, Field, ConfigDict (POS: schema definition)
datetime::datetime (POS: temporal tracking)
enum::StrEnum (POS: category enumeration)

[OUTPUT]
DeltaCategory: enum of ephemeral delta categories (preference, fact, constraint, correction).
EphemeralMemoryDelta: representation of a session-scoped in-flight delta item.
DeltaConsolidationPlan: batch consolidation envelope for post-session disk persistence.
PromptCacheIntegrityMetrics: metrics demonstrating 100% frozen prefix and KV cache preservation.

[POS]
Harness framework layer models for Item 98 (PromptCachePreservingEphemeralDeltaMemorySuite).
Strict typing applied: No `any` types allowed. Single file < 400 lines.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DeltaCategory(StrEnum):
    """Categorization of in-flight ephemeral deltas."""

    PREFERENCE = "preference"
    FACT = "fact"
    CONSTRAINT = "constraint"
    CORRECTION = "correction"


class EphemeralMemoryDelta(BaseModel):
    """A session-scoped in-flight memory delta mounted without breaking prompt prefix cache."""

    model_config = ConfigDict(extra="forbid")

    delta_id: str = Field(description="Unique identifier of this ephemeral delta")
    session_id: str = Field(description="Scoped session identifier")
    category: DeltaCategory = Field(default=DeltaCategory.CORRECTION)
    key: str = Field(description="Entity or attribute key (e.g., user_nickname, api_port)")
    value: str = Field(description="Target updated value or constraint specification")
    raw_instruction: str = Field(default="", description="Original user prompt or tool output triggering this update")
    turn_index: int = Field(default=1, ge=0, description="Turn index in dialog where delta was produced")
    created_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    is_consolidated: bool = Field(default=False, description="True once committed to durable store at session exit")


class DeltaConsolidationPlan(BaseModel):
    """Batch consolidation envelope applied when a session ends or idles."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    deltas_to_commit: list[EphemeralMemoryDelta] = Field(default_factory=list)
    superseded_keys: list[str] = Field(default_factory=list)
    target_storage_tables: list[str] = Field(default_factory=list)
    consolidation_timestamp: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    total_tokens_saved: int = Field(default=0, ge=0)


class PromptCacheIntegrityMetrics(BaseModel):
    """Verification metrics proving prompt cache preservation and immediate recency perception."""

    model_config = ConfigDict(extra="forbid")

    system_prompt_frozen: bool = Field(default=True, description="True if system prompt bytes remained 100% frozen")
    system_prompt_byte_hash: str = Field(description="SHA-256 hash verifying system prompt immutability")
    kv_cache_hit_ratio: float = Field(default=1.0, ge=0.0, le=1.0, description="Measured prompt cache hit fraction")
    in_flight_deltas_count: int = Field(default=0, ge=0, description="Active ephemeral deltas mounted to human tail")
    recency_perception_delay_ms: float = Field(default=0.0, ge=0.0, description="Sub-millisecond latency to apply delta")
    avoided_recomputation_tokens: int = Field(default=0, ge=0, description="Tokens saved by avoiding prefix invalidation")
