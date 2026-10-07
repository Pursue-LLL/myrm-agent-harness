"""Strongly typed contracts for Visual Frame Context Pruning and Latency Squeezing.

[INPUT]
- None (self-contained, standard library only).

[OUTPUT]
- VisualPruningMode: Enumeration defining retention behaviour for visual frames.
- PrunedFrameFootprint: Diagnostic and audit trace of an evicted visual frame.
- VisualPruningConfig: Tunable configuration for sliding-window image eviction.
- VisualPruningResult: Full outcome metrics including token reclamation and cleansed messages.

[POS]
Defines data structures powering multi-modal sliding window eviction,
base64 dehydration, and Computer Use latency optimization.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class VisualPruningMode(str, enum.Enum):
    """Operational mode for sliding window visual frame eviction."""

    SLIDING_WINDOW_STRICT = "sliding_window_strict"
    SLIDING_WINDOW_KEEP_INITIAL = "sliding_window_keep_initial"
    BYPASS = "bypass"


@dataclass(frozen=True, slots=True)
class PrunedFrameFootprint:
    """Audit footprint tracking an evicted image frame and its reclaimed footprint."""

    turn_index: int
    action_summary: str
    reclaimed_bytes: int
    estimated_tokens_saved: int
    eviction_timestamp: float = field(default_factory=time.time)


@dataclass(slots=True)
class VisualPruningConfig:
    """Configuration governing multimodal visual frame retention and dehydration."""

    window_size: int = 2
    mode: VisualPruningMode = VisualPruningMode.SLIDING_WINDOW_STRICT
    placeholder_template: str = "[Image Pruned (Turn {turn}): {summary}]"
    tokens_per_image_estimate: int = 1600
    max_retained_bytes: int = 10 * 1024 * 1024  # 10 MB ceiling

    def is_bypass(self) -> bool:
        """Determines if visual frame pruning is disabled."""
        return self.mode == VisualPruningMode.BYPASS


@dataclass(slots=True)
class VisualPruningResult:
    """Comprehensive outcome of a visual frame pruning cycle."""

    total_images_found: int
    retained_image_count: int
    pruned_image_count: int
    estimated_tokens_saved: int
    reclaimed_bytes: int
    pruned_footprints: list[PrunedFrameFootprint]
    cleansed_messages: list[dict[str, object]]
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, object]:
        """Serializes result metrics to a JSON-compatible dictionary."""
        return {
            "total_images_found": self.total_images_found,
            "retained_image_count": self.retained_image_count,
            "pruned_image_count": self.pruned_image_count,
            "estimated_tokens_saved": self.estimated_tokens_saved,
            "reclaimed_bytes": self.reclaimed_bytes,
            "duration_ms": self.duration_ms,
            "pruned_footprints": [
                {
                    "turn_index": f.turn_index,
                    "action_summary": f.action_summary,
                    "reclaimed_bytes": f.reclaimed_bytes,
                    "estimated_tokens_saved": f.estimated_tokens_saved,
                    "eviction_timestamp": f.eviction_timestamp,
                }
                for f in self.pruned_footprints
            ],
        }
