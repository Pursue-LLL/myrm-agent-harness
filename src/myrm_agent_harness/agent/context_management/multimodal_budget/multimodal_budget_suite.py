"""Master suite for Multi-modal File Image Context Budgeting and Guardian Review.

Coordinates image security screening, precision tile token accounting, and adaptive
downscaling/placeholder compression under context window constraints.

[INPUT]
- agent.context_management.multimodal_budget.image_token_budget_calculator::ImageTokenBudgetCalculator (POS:
  Calculates token expenditure for file images based on tile decomposition geometry.)
- agent.context_management.multimodal_budget.multimodal_budget_types::GuardianReviewResult,
  GuardianVerdictKind, ImageArtifactDescriptor, ImageBudgetAction, ImageBudgetAllocation, ImageDetailMode,
  MultiModalBudgetReport (POS: Data contracts and schemas for multi-modal file image context budgeting and
  Guardian review.)
- agent.context_management.multimodal_budget.multimodal_guardian_reviewer::MultiModalGuardianReviewer (POS:
  Multi-modal Guardian screening image payloads for format validity, size caps, and aspect bounds.)

[OUTPUT]
- MultiModalFileImageContextBudgetAndGuardianReviewSuite: Master suite governing image context budgets and
  Guardian safety enforcement.

[POS]
Master suite for Multi-modal File Image Context Budgeting and Guardian Review.
"""

from __future__ import annotations

from typing import Sequence

from .image_token_budget_calculator import ImageTokenBudgetCalculator
from .multimodal_budget_types import (
    GuardianReviewResult,
    GuardianVerdictKind,
    ImageArtifactDescriptor,
    ImageBudgetAction,
    ImageBudgetAllocation,
    ImageDetailMode,
    MultiModalBudgetReport,
)
from .multimodal_guardian_reviewer import MultiModalGuardianReviewer


class MultiModalFileImageContextBudgetAndGuardianReviewSuite:
    """Master suite governing image context budgets and Guardian safety enforcement."""

    DEFAULT_IMAGE_BUDGET_TOKENS = 4096

    def __init__(self, budget_limit_tokens: int = DEFAULT_IMAGE_BUDGET_TOKENS) -> None:
        self.budget_limit_tokens = budget_limit_tokens
        self._calculator = ImageTokenBudgetCalculator()
        self._guardian = MultiModalGuardianReviewer()
        self._evaluation_history: list[MultiModalBudgetReport] = []

    @property
    def calculator(self) -> ImageTokenBudgetCalculator:
        """Access underlying token calculator."""
        return self._calculator

    @property
    def guardian(self) -> MultiModalGuardianReviewer:
        """Access underlying Guardian safety reviewer."""
        return self._guardian

    def enforce_image_budget(
        self,
        images: Sequence[ImageArtifactDescriptor],
        current_turn_index: int = 0,
        custom_budget_tokens: int | None = None,
    ) -> MultiModalBudgetReport:
        """Screen images and allocate token quotas, applying adaptive compression if budget is exceeded."""
        budget_limit = custom_budget_tokens or self.budget_limit_tokens
        allocations: list[ImageBudgetAllocation] = []
        guardian_results: list[GuardianReviewResult] = []

        # 1. Guardian pre-flight screening
        approved_images: list[ImageArtifactDescriptor] = []
        for img in images:
            review = self._guardian.review_image(img)
            guardian_results.append(review)
            if review.is_safe:
                approved_images.append(img)
            else:
                allocations.append(
                    ImageBudgetAllocation(
                        image_id=img.image_id,
                        estimated_tokens=0,
                        tile_count=0,
                        action=ImageBudgetAction.REJECTED,
                        placeholder_text=f"[Image Rejected by Guardian: {review.reason}]",
                    )
                )

        # 2. Baseline token calculation for approved images
        raw_token_records: list[tuple[ImageArtifactDescriptor, int, int]] = []
        for img in approved_images:
            tokens, tiles = self._calculator.calculate_image_tokens(img.resolution, img.detail_mode)
            raw_token_records.append((img, tokens, tiles))

        total_raw_tokens = sum(t[1] for t in raw_token_records)

        # 3. Budget enforcement and adaptive degradation
        if total_raw_tokens <= budget_limit:
            # Within budget: preserve full resolution for all approved images
            for img, tokens, tiles in raw_token_records:
                allocations.append(
                    ImageBudgetAllocation(
                        image_id=img.image_id,
                        estimated_tokens=tokens,
                        tile_count=tiles,
                        action=ImageBudgetAction.PRESERVE_FULL,
                    )
                )
        else:
            # Over budget: apply tiered adaptive compression
            current_spend = 0
            # Phase A: Degrade historical turns (turn_index < current_turn_index) to light placeholders
            for img, raw_tokens, raw_tiles in raw_token_records:
                if img.turn_index < current_turn_index:
                    placeholder_text = (
                        f"[Historical Image: {img.file_name} ({img.resolution.width}x{img.resolution.height}), "
                        f"~{raw_tokens} tokens compressed to placeholder]"
                    )
                    allocations.append(
                        ImageBudgetAllocation(
                            image_id=img.image_id,
                            estimated_tokens=self._calculator.PLACEHOLDER_TOKENS,
                            tile_count=0,
                            action=ImageBudgetAction.CONVERT_TO_PLACEHOLDER,
                            placeholder_text=placeholder_text,
                        )
                    )
                    current_spend += self._calculator.PLACEHOLDER_TOKENS
                else:
                    # Current turn image: evaluate if downscaling is required
                    if current_spend + raw_tokens <= budget_limit:
                        allocations.append(
                            ImageBudgetAllocation(
                                image_id=img.image_id,
                                estimated_tokens=raw_tokens,
                                tile_count=raw_tiles,
                                action=ImageBudgetAction.PRESERVE_FULL,
                            )
                        )
                        current_spend += raw_tokens
                    else:
                        # Downscale to low detail (85 tokens)
                        low_tokens, _ = self._calculator.calculate_image_tokens(img.resolution, ImageDetailMode.LOW)
                        allocations.append(
                            ImageBudgetAllocation(
                                image_id=img.image_id,
                                estimated_tokens=low_tokens,
                                tile_count=0,
                                action=ImageBudgetAction.DOWNSCALE_LOW_DETAIL,
                            )
                        )
                        current_spend += low_tokens

        total_effective_tokens = sum(a.estimated_tokens for a in allocations)
        is_exceeded = total_effective_tokens > budget_limit

        report = MultiModalBudgetReport(
            total_images=len(images),
            total_image_tokens=total_effective_tokens,
            budget_limit_tokens=budget_limit,
            is_budget_exceeded=is_exceeded,
            allocations=allocations,
            guardian_results=guardian_results,
        )

        self._evaluation_history.append(report)
        return report

    def get_aggregate_stats(self) -> dict[str, int]:
        """Telemetry reporting processed image batches and token savings."""
        total_batches = len(self._evaluation_history)
        total_images = sum(r.total_images for r in self._evaluation_history)
        total_tokens = sum(r.total_image_tokens for r in self._evaluation_history)

        return {
            "total_batches_processed": total_batches,
            "total_images_evaluated": total_images,
            "total_image_tokens_allocated": total_tokens,
        }
