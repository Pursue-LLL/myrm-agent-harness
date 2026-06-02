"""Shared data types for media generation capabilities and normalization.

[OUTPUT]
- MediaTaskState: Common task lifecycle states for media generation
- ModeCapabilities: Per-mode capability declaration (aspect ratios, sizes, durations)
- ProviderModeCapabilities: All three modes for a provider (generate/i2v/v2v)
- NormalizationRecord: Record of a parameter that was normalized to fit provider limits
- SizeSpec: Width/height pair for resolution constraints

[POS]
These types are imported by video/models.py, normalization.py, and task_store.py.
They define the contract between provider declarations and the
normalization engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MediaTaskState(StrEnum):
    """Common task lifecycle states for async media generation."""

    QUEUED = "queued"
    GENERATING = "generating"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SizeSpec:
    """Width/height pair for explicit resolution constraints."""

    width: int
    height: int

    @property
    def aspect_ratio(self) -> float:
        """Width-to-height ratio for distance calculations."""
        return self.width / self.height if self.height > 0 else 0.0


@dataclass(frozen=True, slots=True)
class ModeCapabilities:
    """Capability declaration for a single generation mode (T2V, I2V, or V2V).

    None on ProviderModeCapabilities means the provider does NOT support that mode.
    An empty ModeCapabilities() means the mode is supported with no specific constraints.
    """

    supported_aspect_ratios: tuple[str, ...] = ()
    supported_sizes: tuple[SizeSpec, ...] = ()
    supported_durations: tuple[int, ...] = ()
    default_duration: int | None = None
    max_duration_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class ProviderModeCapabilities:
    """All three modes for a provider. None = mode not supported."""

    generate: ModeCapabilities | None = None
    image_to_video: ModeCapabilities | None = None
    video_to_video: ModeCapabilities | None = None


@dataclass(frozen=True, slots=True)
class NormalizationRecord:
    """Record of a parameter normalized to fit provider/model constraints.

    Included in generation results so LLM/user understands what was adjusted.
    """

    field: str
    requested: str
    applied: str
    reason: str
