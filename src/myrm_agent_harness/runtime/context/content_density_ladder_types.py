"""Type definitions for progressive content density ladder and peek/skim token throttler.

Defines the 4-tier content density ladder (peek, skim, range, full), reading requests,
outline nodes, and token-throttled reading results with lazy object safeguard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class DensityLevel(StrEnum):
    """Four-tier content density hierarchy."""

    PEEK = "peek"    # Tier 1: outline only (headings / function signatures) ~1% tokens
    SKIM = "skim"    # Tier 2: outline + one-line summaries per section ~3-5% tokens
    RANGE = "range"  # Tier 3: targeted line slice [start:end]
    FULL = "full"    # Tier 4: complete content (subject to size ceiling)


@dataclass(frozen=True)
class DensityReadingRequest:
    """Configurable request specifying reading density level and parameters."""

    file_path: str
    level: DensityLevel = DensityLevel.PEEK
    range_start: int | None = None
    range_end: int | None = None
    max_full_size_bytes: int = 50_000


@dataclass(frozen=True)
class DensityOutlineNode:
    """Structural outline symbol node captured from source text."""

    title_or_symbol: str
    node_type: str  # "heading", "class", "function", "section"
    line_number: int
    summary: str | None = None


@dataclass(frozen=True)
class DensityReadingResult:
    """Outcome of token-throttled progressive content reading."""

    file_path: str
    level: DensityLevel
    rendered_content: str
    token_count_estimate: int
    total_file_lines: int
    total_file_bytes: int
    savings_ratio: float
    is_refused: bool = False
    refusal_reason: str | None = None
    outline_nodes: list[DensityOutlineNode] = field(default_factory=list)
