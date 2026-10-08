"""Data models for Conclusion Attribution and Chat Evidence Suite.

Strictly typed, zero Any, providing bidirectional causality and verifiable evidence chains.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class AttributionLevel(StrEnum):
    """Level of attribution indicating how a conclusion was formed."""

    EXPLICIT = "explicit"  # Extracted directly from messages/conversations
    DEDUCTIVE = "deductive"  # Derived via strict deductive reasoning
    INDUCTIVE = "inductive"  # Generalized pattern discovered via inductive synthesis
    CONTRADICTION = "contradiction"  # Formed by reconciling conflicting premises


class MessageReference(BaseModel):
    """Reference to an original chat message supporting the conclusion."""

    message_id: str
    session_id: str
    role: str = "user"
    snippet: str
    timestamp: str | None = None


class ToolCallRecord(BaseModel):
    """Record of a tool call providing empirical ground truth for an answer/conclusion."""

    tool_name: str
    tool_input: dict[str, str] = Field(default_factory=dict)
    tool_output_snippet: str = ""


class AttributedConclusion(BaseModel):
    """Core memory conclusion enriched with causal attribution metadata."""

    id: str
    peer_id: str
    content: str
    level: AttributionLevel = AttributionLevel.EXPLICIT
    source_ids: list[str] = Field(default_factory=list)
    times_derived: int = Field(default=1, ge=1)
    session_id: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: str
    updated_at: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class ChatEvidence(BaseModel):
    """Transparent evidence package returned alongside agent responses."""

    conclusions: list[AttributedConclusion] = Field(default_factory=list)
    messages: list[MessageReference] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    reasoning_trace_id: str | None = None


class GraphTraversalNode(BaseModel):
    """Single node within a reasoning graph hierarchy."""

    conclusion: AttributedConclusion
    depth: int = 0
    direct_parent_ids: list[str] = Field(default_factory=list)
    direct_child_ids: list[str] = Field(default_factory=list)


class RippleImpactReport(BaseModel):
    """Analysis of consequences when modifying or retracting a conclusion."""

    target_conclusion_id: str
    impacted_conclusion_ids: list[str] = Field(default_factory=list)
    depth_reached: int = 0
    severity: Literal["low", "medium", "high", "critical"] = "low"
    explanation: str = ""


class AttributionMetrics(BaseModel):
    """Aggregate telemetry of memory attribution health."""

    total_conclusions: int = 0
    explicit_count: int = 0
    deductive_count: int = 0
    inductive_count: int = 0
    contradiction_count: int = 0
    max_derivation_depth: int = 0
    average_times_derived: float = 1.0
