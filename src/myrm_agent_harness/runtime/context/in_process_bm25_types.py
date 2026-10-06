"""Type definitions for In-Process BM25 Lexical Retriever and Dynamic Tool Schema Pruner.

Reference: ratel-ai Context Engineering for AI Agents (~80% fewer tokens).
Strict 0 Any, immutable frozen dataclasses for progressive tool disclosure.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class BM25Document:
    """Document indexed by the in-process BM25 lexical engine."""

    doc_id: str
    content: str
    tokens: tuple[str, ...]
    metadata: Mapping[str, str | int | float | bool]


@dataclass(frozen=True)
class BM25SearchResult:
    """Search hit returned by BM25 scoring."""

    doc_id: str
    score: float
    rank: int
    snippet: str


@dataclass(frozen=True)
class ToolSchemaEntry:
    """Registered tool specification eligible for dynamic progressive disclosure."""

    name: str
    description: str
    parameters_schema_json: str
    category: str = "general"
    is_core: bool = False
    keywords: tuple[str, ...] = ()

    @property
    def estimated_tokens(self) -> int:
        """Estimate token consumption of this tool schema (heuristic chars // 4)."""
        total_chars = len(self.name) + len(self.description) + len(self.parameters_schema_json)
        return max(1, total_chars // 4)


@dataclass(frozen=True)
class PrunedToolSet:
    """Result of progressive tool schema pruning for a given turn."""

    active_tools: tuple[ToolSchemaEntry, ...]
    pruned_tool_names: tuple[str, ...]
    original_token_estimate: int
    pruned_token_estimate: int
    token_saving_ratio: float
    expansion_directive: str


@dataclass(frozen=True)
class ProgressiveDisclosureConfig:
    """Configuration governing dynamic tool schema pruning."""

    top_k: int = 4
    core_tool_names: tuple[str, ...] = ("read_file", "write_file", "run_command")
    min_score_threshold: float = 0.05
    allow_dynamic_expansion: bool = True
    k1: float = 1.5
    b: float = 0.75
