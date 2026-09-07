"""Domain types and configurations for transparent content spillover.

[INPUT]
- typing: Any, Optional, Dict, List
- dataclasses: dataclass, field

[OUTPUT]
- SpilloverConfig: Configuration for spillover thresholds and directories.
- SpilloverPayload: Metadata and content representation of spilled document.
- SpilloverResult: Outcome of the spillover evaluation and file persistence.

[POS]
Harness domain types for context bomb defense and transparent spillover.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class SpilloverConfig:
    """Configuration for message size thresholds and spillover storage."""

    max_chars: int = 16_000
    summary_head_chars: int = 300
    summary_tail_chars: int = 100
    spillover_dir_name: str = ".myrm/spillover"
    stale_ttl_seconds: float = 86_400.0  # 24 hours


@dataclass(slots=True)
class SpilloverPayload:
    """Descriptor of spilled document saved to the workspace filesystem."""

    file_path: str
    relative_path: str
    total_chars: int
    total_lines: int
    sha256_digest: str
    head_preview: str
    tail_preview: str
    created_at: float


@dataclass(slots=True)
class SpilloverResult:
    """Result of evaluating and potentially spilling an oversized message."""

    is_spilled: bool
    original_chars: int
    transformed_content: str
    payload: SpilloverPayload | None = None
    system_guide_prompt: str | None = None
