"""Type definitions for Sandwich Trajectory Compression and Middle Turn Summarization.

Provides immutable data contracts for three-zone keyframe partitioning (head/middle/tail),
target token budgets, and structured middle trajectory compression results.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TrajectoryCompressionConfig:
    """Configuration governing sandwich trajectory compression budgets and protection zones."""

    target_max_tokens: int = 16000
    head_protect_turns: int = 1
    tail_protect_turns: int = 3
    max_middle_summary_tokens: int = 1000
    max_tool_output_chars_in_middle: int = 500


@dataclass(frozen=True)
class SandwichPartition:
    """Keyframe partition splitting context into head, middle, and tail regions."""

    head_messages: tuple[dict[str, str], ...]
    middle_messages: tuple[dict[str, str], ...]
    tail_messages: tuple[dict[str, str], ...]
    head_token_count: int
    middle_token_count: int
    tail_token_count: int
    total_token_count: int


@dataclass(frozen=True)
class CompressionResult:
    """Result emitted after evaluating and executing sandwich trajectory compression."""

    is_compressed: bool
    original_tokens: int
    compacted_tokens: int
    reclaimed_tokens: int
    head_preserved_count: int
    tail_preserved_count: int
    middle_absorbed_count: int
    summary_inserted: bool
