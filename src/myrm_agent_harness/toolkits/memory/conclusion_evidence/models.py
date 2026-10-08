"""Domain models for conclusion attribution and chat evidence verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from time import time


class AttributionLevel(StrEnum):
    """Reasoning attribution classification of a conclusion."""

    EXPLICIT = "explicit"  # Directly declared or extracted from explicit user messages
    DEDUCTIVE = "deductive"  # Derived via formal deductive logic from premises
    INDUCTIVE = "inductive"  # Generalized or pattern-matched from repeated observations
    ABDUCTIVE = "abductive"  # Hypothesized as the most likely explanation
    CONTRADICTION = "contradiction"  # Synthesized during conflict resolution or arbitration


class DerivationCycleError(Exception):
    """Raised when registering a conclusion would create a cyclic dependency in the DAG."""


@dataclass(frozen=True)
class AttributedConclusion:
    """Normative conclusion object carrying rich attribution and causality metadata."""

    conclusion_id: str
    peer_id: str
    content: str
    level: AttributionLevel = AttributionLevel.EXPLICIT
    source_ids: tuple[str, ...] = field(default_factory=tuple)  # Premise conclusion IDs
    times_derived: int = 1  # Frequency of independent reproduction
    evidence_message_ids: tuple[str, ...] = field(default_factory=tuple)
    scope_tag: str = "general"
    status: str = "confirmed"
    created_at: float = field(default_factory=time)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MessageEvidenceItem:
    """Verifiable message evidence snapshot snippet."""

    message_id: str
    session_id: str
    peer_id: str
    content_snippet: str
    timestamp: float = field(default_factory=time)


@dataclass(frozen=True)
class ToolCallEvidenceItem:
    """Verifiable tool execution evidence record."""

    tool_name: str
    tool_input: dict[str, str] = field(default_factory=dict)
    tool_output: str = ""


@dataclass(frozen=True)
class ChatEvidenceBundle:
    """Evidence bundle returned when include_evidence is enabled."""

    conclusions: tuple[AttributedConclusion, ...] = field(default_factory=tuple)
    messages: tuple[MessageEvidenceItem, ...] = field(default_factory=tuple)
    tool_calls: tuple[ToolCallEvidenceItem, ...] = field(default_factory=tuple)
    reasoning_trace_id: str | None = None


@dataclass(frozen=True)
class DerivationTraversalView:
    """Two-way causal traversal view anchored at a specific conclusion."""

    conclusion_id: str
    upstream_premises: tuple[AttributedConclusion, ...] = field(default_factory=tuple)
    downstream_derivatives: tuple[AttributedConclusion, ...] = field(default_factory=tuple)
    max_depth: int = 1


@dataclass(frozen=True)
class ConclusionEvidenceStats:
    """Overall health and topology statistics of attributed conclusions."""

    total_conclusions: int
    total_explicit: int
    total_derived: int
    total_edges: int
    max_derivation_depth: int
