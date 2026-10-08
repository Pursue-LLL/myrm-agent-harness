"""Data contracts and schemas for multi-modal file image context budgeting and Guardian review.

Defines resolution geometry, tile token calculations, Guardian safety verdicts,
and adaptive downscaling/placeholder compression actions.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- ImageDetailMode: Fidelity mode governing visual resolution token calculations.
- GuardianVerdictKind: Evaluation verdict from multi-modal Guardian pre-flight screening.
- ImageBudgetAction: Enforcement action applied to an image artifact under context constraints.
- ImageResolution: Width and height dimensions in pixels.
- ImageArtifactDescriptor: Descriptor of a file image attached to the conversational context.
- GuardianReviewResult: Outcome of multi-modal Guardian safety and format screening.
- ImageBudgetAllocation: Token quota assignment and resulting enforcement action for an image.
- MultiModalBudgetReport: Consolidated report tracking multi-modal image token spend and Guardian reviews.

[POS]
Data contracts and schemas for multi-modal file image context budgeting and Guardian review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ImageDetailMode(StrEnum):
    """Fidelity mode governing visual resolution token calculations."""

    LOW = "low"
    HIGH = "high"
    AUTO = "auto"


class GuardianVerdictKind(StrEnum):
    """Evaluation verdict from multi-modal Guardian pre-flight screening."""

    PASS = "pass"
    REJECT_UNSUPPORTED_FORMAT = "reject_unsupported_format"
    REJECT_SIZE_LIMIT = "reject_size_limit"
    REJECT_EXTREME_ASPECT_RATIO = "reject_extreme_aspect_ratio"
    REJECT_INVALID_DIMENSIONS = "reject_invalid_dimensions"


class ImageBudgetAction(StrEnum):
    """Enforcement action applied to an image artifact under context constraints."""

    PRESERVE_FULL = "preserve_full"
    DOWNSCALE_LOW_DETAIL = "downscale_low_detail"
    CONVERT_TO_PLACEHOLDER = "convert_to_placeholder"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ImageResolution:
    """Width and height dimensions in pixels."""

    width: int
    height: int


@dataclass(frozen=True)
class ImageArtifactDescriptor:
    """Descriptor of a file image attached to the conversational context."""

    image_id: str
    file_name: str
    format: str
    size_bytes: int
    resolution: ImageResolution
    turn_index: int
    detail_mode: ImageDetailMode = ImageDetailMode.AUTO


@dataclass(frozen=True)
class GuardianReviewResult:
    """Outcome of multi-modal Guardian safety and format screening."""

    image_id: str
    verdict: GuardianVerdictKind
    is_safe: bool
    reason: str


@dataclass(frozen=True)
class ImageBudgetAllocation:
    """Token quota assignment and resulting enforcement action for an image."""

    image_id: str
    estimated_tokens: int
    tile_count: int
    action: ImageBudgetAction
    placeholder_text: str | None = None


@dataclass(frozen=True)
class MultiModalBudgetReport:
    """Consolidated report tracking multi-modal image token spend and Guardian reviews."""

    total_images: int
    total_image_tokens: int
    budget_limit_tokens: int
    is_budget_exceeded: bool
    allocations: list[ImageBudgetAllocation]
    guardian_results: list[GuardianReviewResult]
