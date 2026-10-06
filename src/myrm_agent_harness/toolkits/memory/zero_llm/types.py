"""Type definitions for zero-LLM local memory capture and rule-based FTS graph retrieval.

Defines typed categories for zero-cost fact extraction, search hits with topological
graph distance metrics, and progressive enhancement configuration.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class FactCategory(StrEnum):
    """Categorization for facts extracted via deterministic rules."""

    PREFERENCE = "preference"
    CONFIGURATION = "configuration"
    TOOL_OUTCOME = "tool_outcome"
    DECISION = "decision"
    ENTITY = "entity"
    DEPENDENCY = "dependency"


class LlmAugmentationMode(StrEnum):
    """Augmentation mode for progressive enhancement."""

    DISABLED = "disabled"
    OPTIONAL = "optional"
    ENHANCED = "enhanced"


class ExtractedRuleFact(BaseModel):
    """A structured memory fact extracted entirely without LLM inference."""

    fact_id: str = Field(description="Deterministic or unique identifier for the fact")
    category: FactCategory = Field(description="Semantic category of the fact")
    subject: str = Field(description="Subject entity or concept")
    predicate: str = Field(description="Relationship or action connecting subject and value")
    object_value: str = Field(description="Value, constraint, or target entity")
    confidence: float = Field(ge=0.0, le=1.0, description="Rule confidence score (0.0 to 1.0)")
    evidence_snippet: str = Field(description="Exact verbatim excerpt that triggered the rule")
    source_turn_index: int = Field(default=0, ge=0, description="Conversation turn index")
    source_file: str | None = Field(default=None, description="Optional source file path")


class FtsGraphSearchHit(BaseModel):
    """Search match combining FTS5 lexical ranking with wikilink graph topology."""

    page_slug: str = Field(description="Wiki memory page slug or identifier")
    title: str = Field(description="Title of the matched memory document")
    snippet: str = Field(description="Relevant text snippet or summary")
    fts_score: float = Field(description="BM25 / FTS lexical rank score")
    graph_hops: int = Field(ge=0, description="Topological distance from primary match (0 = direct)")
    composite_score: float = Field(description="Final unified score considering graph hop decay")
    linked_entities: list[str] = Field(default_factory=list, description="Extracted wikilink target entities")


class ZeroLlmSearchResult(BaseModel):
    """Aggregated retrieval results executed with zero LLM API cost."""

    query: str = Field(description="Original search query string")
    hits: list[FtsGraphSearchHit] = Field(default_factory=list, description="Ranked hit items")
    total_hits: int = Field(ge=0, description="Total matching documents found")
    zero_token_cost: bool = Field(default=True, description="Always true indicating 0 API tokens consumed")


class ExtractionBatchResult(BaseModel):
    """Summary of batch rule extraction across one or multiple turns."""

    facts: list[ExtractedRuleFact] = Field(default_factory=list, description="Extracted fact collection")
    total_extracted: int = Field(ge=0, description="Number of unique facts extracted")
    turn_count: int = Field(ge=0, description="Number of turns processed")
    zero_token_cost: bool = Field(default=True, description="Always true indicating 0 API tokens consumed")


class ZeroLlmConfig(BaseModel):
    """Configuration options for Zero-LLM memory engine."""

    enabled: bool = Field(default=True, description="Enable deterministic zero-cost capture")
    min_confidence: float = Field(default=0.6, ge=0.0, le=1.0, description="Minimum confidence threshold")
    max_facts_per_turn: int = Field(default=20, ge=1, le=100, description="Maximum facts to keep per turn")
    fts_limit: int = Field(default=10, ge=1, le=50, description="Maximum direct FTS matches to retrieve")
    graph_hop_decay: float = Field(default=0.5, ge=0.1, le=1.0, description="Topological distance decay factor")
    augmentation_mode: LlmAugmentationMode = Field(
        default=LlmAugmentationMode.OPTIONAL,
        description="Whether LLM progressive enhancement is disabled, optional, or enhanced",
    )
