"""[POS]: src/myrm_agent_harness/toolkits/memory/directory_dominance/models.py
[INPUT]: Hierarchy node structures, query parameters, and dominance ratio configurations.
[OUTPUT]: Strongly typed domain models for hierarchical directory dominance retrieval and sibling context bundling.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class HierarchyNodeType(StrEnum):
    """Classification of nodes in the context hierarchy."""

    DIRECTORY = "directory"
    FILE = "file"
    CHUNK = "chunk"


class DominanceDecisionKind(StrEnum):
    """Retriever decision outcomes regarding tree exploration."""

    DIRECTORY_DOMINANT = "directory_dominant"
    LEAF_SPECIFIC = "leaf_specific"
    BALANCED = "balanced"


class DirectoryDominanceConfig(BaseModel):
    """Configuration governing hierarchical dominance ratio and exploration limits."""

    dominance_ratio: float = Field(
        default=1.2,
        ge=1.0,
        le=5.0,
        description="Ratio threshold (dir_score >= max_child_score * ratio) to declare directory dominance",
    )
    max_convergence_rounds: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum iterations allowed for hierarchical search convergence",
    )
    max_parallel_child_searches: int = Field(
        default=4,
        ge=1,
        le=20,
        description="Fan-out cap on child subtrees explored per directory",
    )
    max_siblings_per_hit: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum number of sibling abstracts bundled with a localized hit",
    )
    include_parent_context: bool = Field(
        default=True,
        description="Whether to bundle parent directory overview into hit payload",
    )
    min_score_threshold: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum score required for candidate consideration",
    )


class HierarchicalNode(BaseModel):
    """Single node in the hierarchical context tree."""

    uri: str = Field(..., description="Canonical URI identifier of the node (e.g. context://resources/auth/oauth.py)")
    node_type: HierarchyNodeType = Field(..., description="Node classification (directory, file, chunk)")
    name: str = Field(..., description="Display or path segment name")
    parent_uri: str | None = Field(default=None, description="Canonical URI of parent directory if present")
    children_uris: list[str] = Field(default_factory=list, description="List of immediate children URIs")
    abstract: str = Field(default="", description="L0 compact abstract or description")
    content: str = Field(default="", description="L1 overview or full payload")
    score: float = Field(default=0.0, ge=0.0, description="Relevance score for the target query")


class SiblingContextItem(BaseModel):
    """Bundled sibling node context to prevent isolated fragmentation."""

    uri: str = Field(..., description="Sibling canonical URI")
    name: str = Field(..., description="Sibling node display name")
    abstract: str = Field(..., description="L0 compact summary of sibling")
    relation: str = Field(default="sibling", description="Relational link descriptor")


class HierarchicalRetrievalHit(BaseModel):
    """Augmented retrieval hit containing hierarchical context and sibling bundles."""

    uri: str = Field(..., description="Hit canonical URI")
    node_type: HierarchyNodeType = Field(..., description="Type of node")
    score: float = Field(..., ge=0.0, description="Final resolved relevance score")
    decision: DominanceDecisionKind = Field(..., description="Dominance classification that produced this hit")
    abstract: str = Field(default="", description="L0 abstract of the matched node")
    content: str = Field(default="", description="Overview or detail content")
    parent_uri: str | None = Field(default=None, description="Parent directory URI")
    parent_summary: str | None = Field(default=None, description="Parent directory overview if enabled")
    sibling_contexts: list[SiblingContextItem] = Field(
        default_factory=list,
        description="Bundled sibling abstracts",
    )


class HierarchicalRetrievalStats(BaseModel):
    """Execution telemetry and metrics for hierarchical dominance retrieval."""

    convergence_rounds: int = Field(default=1, ge=1, description="Executed convergence iterations")
    nodes_evaluated: int = Field(default=0, ge=0, description="Total nodes scored or inspected")
    dominant_directories_count: int = Field(default=0, ge=0, description="Directories winning dominance test")
    leaf_hits_count: int = Field(default=0, ge=0, description="Individual leaf/file hits emitted")
    total_siblings_bundled: int = Field(default=0, ge=0, description="Total sibling context snippets attached")


class HierarchicalRetrievalResult(BaseModel):
    """Final aggregated result of hierarchical directory dominance retrieval."""

    query: str = Field(..., description="Target search query")
    hits: list[HierarchicalRetrievalHit] = Field(default_factory=list, description="Resolved ranked hits")
    stats: HierarchicalRetrievalStats = Field(
        default_factory=HierarchicalRetrievalStats,
        description="Telemetry and convergence statistics",
    )
