from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from myrm_agent_harness.toolkits.retriever.relaxed_arm_fusion_types import (
    AdaptiveFusionResult,
    AdaptiveReturnConfig,
    ArmTelemetryProfile,
    FusedArmHit,
    RetrievalArm,
)


class ArmNoiseDetector:
    """Evaluates peak sharpness, entropy variance, and signal-to-noise ratio per retrieval arm."""

    @staticmethod
    def evaluate_arm[T](
        arm: RetrievalArm[T],
        config: AdaptiveReturnConfig,
    ) -> tuple[bool, float, float, float, float]:
        """Detect whether an arm is polluted with flat, noisy candidates.

        Returns: (is_demoted, peak_score, mean_score, sharpness_gap, variance)
        """
        if not arm.candidates:
            return False, 0.0, 0.0, 0.0, 0.0

        scores = [c.score for c in arm.candidates]
        peak_score = max(scores)
        mean_score = sum(scores) / len(scores)
        variance = sum((s - mean_score) ** 2 for s in scores) / len(scores)
        sharpness_gap = peak_score - mean_score

        # If candidates count >= 3 and sharpness gap is below threshold, the distribution is flat/noisy
        is_demoted = len(scores) >= 3 and sharpness_gap < config.min_sharpness_gap
        return is_demoted, peak_score, mean_score, sharpness_gap, variance


class RelaxedArmFusionEngine[T]:
    """Adaptive multi-arm retriever fusion engine with dynamic demotion and volunteer activation."""

    def __init__(self, config: AdaptiveReturnConfig | None = None) -> None:
        self._config = config or AdaptiveReturnConfig()

    @property
    def config(self) -> AdaptiveReturnConfig:
        return self._config

    def fuse(
        self,
        arms: Sequence[RetrievalArm[T]],
    ) -> AdaptiveFusionResult[T]:
        """Fuse candidate ranked lists across multiple arms with dynamic noise demotion."""
        if not arms:
            return AdaptiveFusionResult(
                hits=[],
                arm_telemetry=[],
                volunteer_activated=False,
                demoted_arms=[],
            )

        core_arms = [a for a in arms if not a.is_volunteer]
        volunteer_arms = [a for a in arms if a.is_volunteer]

        telemetry_profiles: list[ArmTelemetryProfile] = []
        effective_weights: dict[str, float] = {}
        demoted_arm_names: list[str] = []

        # Step 1: Detect noise & assign dynamic demoted weights to core arms
        for arm in core_arms:
            is_demoted, peak, mean, gap, var = ArmNoiseDetector.evaluate_arm(arm, self._config)
            eff_weight = arm.base_weight * (self._config.demotion_factor if is_demoted else 1.0)
            if is_demoted:
                demoted_arm_names.append(arm.name)

            effective_weights[arm.name] = eff_weight
            telemetry_profiles.append(
                ArmTelemetryProfile(
                    arm_name=arm.name,
                    arm_kind=arm.arm_kind,
                    raw_count=len(arm.candidates),
                    peak_score=peak,
                    mean_score=mean,
                    sharpness_gap=gap,
                    variance=var,
                    is_demoted=is_demoted,
                    effective_weight=eff_weight,
                    contributed_items_count=0,
                )
            )

        # Step 2: Determine if volunteer arm activation is necessary
        unique_core_keys = {c.key for a in core_arms for c in a.candidates if c.score > 0.0}
        needs_volunteer = len(unique_core_keys) < self._config.min_core_items and len(volunteer_arms) > 0

        active_arms: list[RetrievalArm[T]] = list(core_arms)
        if needs_volunteer:
            for v_arm in volunteer_arms:
                _, v_peak, v_mean, v_gap, v_var = ArmNoiseDetector.evaluate_arm(v_arm, self._config)
                v_weight = v_arm.base_weight * self._config.volunteer_boost
                effective_weights[v_arm.name] = v_weight
                active_arms.append(v_arm)

                telemetry_profiles.append(
                    ArmTelemetryProfile(
                        arm_name=v_arm.name,
                        arm_kind=v_arm.arm_kind,
                        raw_count=len(v_arm.candidates),
                        peak_score=v_peak,
                        mean_score=v_mean,
                        sharpness_gap=v_gap,
                        variance=v_var,
                        is_demoted=False,
                        effective_weight=v_weight,
                        contributed_items_count=0,
                    )
                )

        # Step 3: Weighted RRF Score Aggregation
        item_registry: dict[str, T] = {}
        rrf_scores: defaultdict[str, float] = defaultdict(float)
        arm_contributions: defaultdict[str, list[str]] = defaultdict(list)
        arm_contributed_counts: defaultdict[str, int] = defaultdict(int)

        k = self._config.rrf_k
        non_empty_active_arms = [a for a in active_arms if a.candidates]

        if not non_empty_active_arms:
            return AdaptiveFusionResult(
                hits=[],
                arm_telemetry=telemetry_profiles,
                volunteer_activated=needs_volunteer,
                demoted_arms=demoted_arm_names,
            )

        max_possible_rrf = sum(
            effective_weights.get(a.name, 1.0) / (k + 1) for a in non_empty_active_arms
        )
        if max_possible_rrf <= 0.0:
            max_possible_rrf = 1.0 / (k + 1)

        for arm in non_empty_active_arms:
            weight = effective_weights.get(arm.name, 1.0)
            for idx, candidate in enumerate(arm.candidates):
                rank = candidate.rank if candidate.rank > 0 else (idx + 1)
                item_registry[candidate.key] = candidate.item
                contrib = weight / (k + rank)
                rrf_scores[candidate.key] += contrib
                arm_contributions[candidate.key].append(arm.name)
                arm_contributed_counts[arm.name] += 1

        # Step 4: Deterministic ranking and normalization
        ranked_keys = sorted(
            rrf_scores.keys(),
            key=lambda key: (-round(rrf_scores[key], 9), -len(arm_contributions[key]), key),
        )

        fused_hits: list[FusedArmHit[T]] = []
        volunteer_arm_names = {v.name for v in volunteer_arms}

        for key in ranked_keys[: self._config.target_top_k]:
            raw_rrf = rrf_scores[key]
            norm_score = min(1.0, (raw_rrf / max_possible_rrf) * self._config.normalize_target)
            hit_arms = arm_contributions[key]
            is_volunteer_fallback = bool(hit_arms and all(a in volunteer_arm_names for a in hit_arms))

            fused_hits.append(
                FusedArmHit(
                    item=item_registry[key],
                    key=key,
                    score=norm_score,
                    raw_rrf_score=raw_rrf,
                    contributing_arms=hit_arms,
                    is_volunteer_fallback=is_volunteer_fallback,
                )
            )

        # Update telemetry contributed items counts
        updated_telemetry: list[ArmTelemetryProfile] = []
        for profile in telemetry_profiles:
            updated_telemetry.append(
                ArmTelemetryProfile(
                    arm_name=profile.arm_name,
                    arm_kind=profile.arm_kind,
                    raw_count=profile.raw_count,
                    peak_score=profile.peak_score,
                    mean_score=profile.mean_score,
                    sharpness_gap=profile.sharpness_gap,
                    variance=profile.variance,
                    is_demoted=profile.is_demoted,
                    effective_weight=profile.effective_weight,
                    contributed_items_count=arm_contributed_counts[profile.arm_name],
                )
            )

        return AdaptiveFusionResult(
            hits=fused_hits,
            arm_telemetry=updated_telemetry,
            volunteer_activated=needs_volunteer,
            demoted_arms=demoted_arm_names,
        )
