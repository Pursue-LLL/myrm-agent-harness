"""Unit tests for Multi-Modal File Image Context Budget and Guardian Review Suite.

Verifies tile-based image token estimation geometry, Guardian security invariants
(unsupported format, file size limits, extreme aspect ratios), adaptive placeholder
compression for historical turns, and low-detail downscaling under quota pressure.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management import (
    GuardianReviewResult,
    GuardianVerdictKind,
    ImageArtifactDescriptor,
    ImageBudgetAction,
    ImageBudgetAllocation,
    ImageDetailMode,
    ImageResolution,
    ImageTokenBudgetCalculator,
    MultiModalBudgetReport,
    MultiModalFileImageContextBudgetAndGuardianReviewSuite,
    MultiModalGuardianReviewer,
)


def test_image_token_budget_calculator_geometry_and_modes() -> None:
    """Verify tile decomposition token calculation across detail modes and resolutions."""
    calc = ImageTokenBudgetCalculator()

    # 1. Low detail mode always returns base 85 tokens
    low_tokens, low_tiles = calc.calculate_image_tokens(
        resolution=ImageResolution(width=1920, height=1080),
        detail_mode=ImageDetailMode.LOW,
    )
    assert low_tokens == 85
    assert low_tiles == 0

    # 2. Standard resolution in AUTO mode
    std_tokens, std_tiles = calc.calculate_image_tokens(
        resolution=ImageResolution(width=1024, height=768),
        detail_mode=ImageDetailMode.AUTO,
    )
    assert std_tiles > 0
    assert std_tokens == std_tiles * 170 + 85

    # 3. 4K high resolution scaled within bounding bounds
    huge_tokens, huge_tiles = calc.calculate_image_tokens(
        resolution=ImageResolution(width=3840, height=2160),
        detail_mode=ImageDetailMode.HIGH,
    )
    assert huge_tiles >= 4
    assert huge_tokens == huge_tiles * 170 + 85


def test_multimodal_guardian_reviewer_invariants() -> None:
    """Verify Guardian security boundary screening against bad formats, large files, and distorted ratios."""
    guardian = MultiModalGuardianReviewer()

    # 1. Normal valid image passes
    valid_desc = ImageArtifactDescriptor(
        image_id="img-001",
        file_name="screenshot.png",
        format="png",
        size_bytes=1024 * 500,  # 500 KiB
        resolution=ImageResolution(width=1280, height=720),
        turn_index=1,
    )
    rev_valid = guardian.review_image(valid_desc)
    assert rev_valid.is_safe
    assert rev_valid.verdict == GuardianVerdictKind.PASS

    # 2. Unsupported format rejected
    bad_fmt_desc = ImageArtifactDescriptor(
        image_id="img-002",
        file_name="malware.exe",
        format="exe",
        size_bytes=1024,
        resolution=ImageResolution(width=100, height=100),
        turn_index=1,
    )
    rev_fmt = guardian.review_image(bad_fmt_desc)
    assert not rev_fmt.is_safe
    assert rev_fmt.verdict == GuardianVerdictKind.REJECT_UNSUPPORTED_FORMAT

    # 3. Size limit exceeded
    oversized_desc = ImageArtifactDescriptor(
        image_id="img-003",
        file_name="giant.jpg",
        format="jpg",
        size_bytes=25 * 1024 * 1024,  # 25 MiB > 20 MiB limit
        resolution=ImageResolution(width=1000, height=1000),
        turn_index=1,
    )
    rev_size = guardian.review_image(oversized_desc)
    assert not rev_size.is_safe
    assert rev_size.verdict == GuardianVerdictKind.REJECT_SIZE_LIMIT

    # 4. Extreme aspect ratio rejected (e.g. 2000x50 = 40:1)
    aspect_desc = ImageArtifactDescriptor(
        image_id="img-004",
        file_name="strip.webp",
        format="webp",
        size_bytes=1024 * 100,
        resolution=ImageResolution(width=2000, height=50),
        turn_index=1,
    )
    rev_aspect = guardian.review_image(aspect_desc)
    assert not rev_aspect.is_safe
    assert rev_aspect.verdict == GuardianVerdictKind.REJECT_EXTREME_ASPECT_RATIO


def test_multimodal_budget_suite_enforcement_and_adaptive_degradation() -> None:
    """Verify adaptive compression of historical turn images and low-detail fallback under quota."""
    suite = MultiModalFileImageContextBudgetAndGuardianReviewSuite(budget_limit_tokens=1500)

    # Prepare images: 2 historical images + 1 current turn image + 1 invalid format image
    images = [
        ImageArtifactDescriptor(
            image_id="img-hist-1",
            file_name="old_chart1.png",
            format="png",
            size_bytes=200_000,
            resolution=ImageResolution(width=1920, height=1080),
            turn_index=0,
        ),
        ImageArtifactDescriptor(
            image_id="img-hist-2",
            file_name="old_chart2.png",
            format="png",
            size_bytes=200_000,
            resolution=ImageResolution(width=1920, height=1080),
            turn_index=1,
        ),
        ImageArtifactDescriptor(
            image_id="img-curr",
            file_name="current_mockup.png",
            format="png",
            size_bytes=400_000,
            resolution=ImageResolution(width=1280, height=720),
            turn_index=2,
        ),
        ImageArtifactDescriptor(
            image_id="img-bad",
            file_name="corrupt.tiff",
            format="tiff",
            size_bytes=1000,
            resolution=ImageResolution(width=200, height=200),
            turn_index=2,
        ),
    ]

    report = suite.enforce_image_budget(
        images=images,
        current_turn_index=2,
        custom_budget_tokens=1200,
    )

    assert report.total_images == 4
    assert not report.is_budget_exceeded

    # Verify allocations
    alloc_map = {a.image_id: a for a in report.allocations}

    # 1. Historical images compressed to placeholder (~20 tokens)
    assert alloc_map["img-hist-1"].action == ImageBudgetAction.CONVERT_TO_PLACEHOLDER
    assert alloc_map["img-hist-1"].estimated_tokens == 20
    assert "[Historical Image" in (alloc_map["img-hist-1"].placeholder_text or "")

    assert alloc_map["img-hist-2"].action == ImageBudgetAction.CONVERT_TO_PLACEHOLDER
    assert alloc_map["img-hist-2"].estimated_tokens == 20

    # 2. Current turn image preserved full resolution within remaining quota
    assert alloc_map["img-curr"].action == ImageBudgetAction.PRESERVE_FULL
    assert alloc_map["img-curr"].estimated_tokens > 200

    # 3. Invalid format image rejected by Guardian
    assert alloc_map["img-bad"].action == ImageBudgetAction.REJECTED
    assert alloc_map["img-bad"].estimated_tokens == 0

    # 4. Telemetry stats
    stats = suite.get_aggregate_stats()
    assert stats["total_batches_processed"] == 1
    assert stats["total_images_evaluated"] == 4
