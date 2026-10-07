"""Type definitions and contracts for Token-Budget-Aware Code Memory Compaction.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- CodeAbstractionLevel: Hierarchical abstraction tiers for source code memory compression.
- CodeBlockItem: Input representation of a code file or snippet to be compacted.
- CompactedBlock: Compacted representation of a single code block.
- CompactionConfig: Configuration options for the Token-Budget-Aware Code Compaction Engine.
- CompactionResult: Outcome of budget-guided code memory compaction across multiple files.

[POS]
Type definitions and contracts for Token-Budget-Aware Code Memory Compaction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class CodeAbstractionLevel(StrEnum):
    """Hierarchical abstraction tiers for source code memory compression."""

    L1_SIGNATURES = "L1_SIGNATURES"  # Signatures and types only (~85% compression)
    L2_CONTROL_FLOW = "L2_CONTROL_FLOW"  # Signatures, docstrings, control flow skeleton (~60% compression)
    L3_FULL_SOURCE = "L3_FULL_SOURCE"  # Original unmodified source code


@dataclass(frozen=True)
class CodeBlockItem:
    """Input representation of a code file or snippet to be compacted."""

    file_path: str
    source_code: str
    relevance_score: float = 1.0
    language: str = "python"


@dataclass(frozen=True)
class CompactedBlock:
    """Compacted representation of a single code block."""

    file_path: str
    abstraction_level: CodeAbstractionLevel
    content: str
    original_token_count: int
    compacted_token_count: int


@dataclass(frozen=True)
class CompactionConfig:
    """Configuration options for the Token-Budget-Aware Code Compaction Engine."""

    token_budget: int = 1500
    min_level: CodeAbstractionLevel = CodeAbstractionLevel.L1_SIGNATURES
    strip_private_symbols: bool = False
    tokens_per_char_ratio: float = 0.26  # Approximation for BPE/tiktoken code tokens


@dataclass(frozen=True)
class CompactionResult:
    """Outcome of budget-guided code memory compaction across multiple files."""

    compacted_blocks: list[CompactedBlock] = field(default_factory=list)
    total_original_tokens: int = 0
    total_compacted_tokens: int = 0
    budget_limit: int = 1500
    compression_ratio: float = 0.0
