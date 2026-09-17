"""Skill Specialized Model Resolver — Model-As-A-Skill Hybrid Engine.

Resolves specialized model configurations declared by skills, providing deterministic
tier mapping, model slug resolution, local/cloud fallback chains, and sub-task offloading.

[INPUT]
- skill_metadata: SkillMetadata (Metadata containing specialized_model and model_tier)
- available_models: list[str] | set[str] | None (Optional whitelist of available models)
- default_model: str (Host agent default model fallback)
- tier_model_map: dict[str, str] | None (Mapping from tier "simple" | "standard" | "reasoning" to model slugs)

[OUTPUT]
- SkillModelResolutionResult: Dataclass (selected_model, model_tier, resolution_source, is_fallback, reason)
- SkillModelResolver: Resolver class with resolve_skill_model() method

[POS]
Harness framework layer: backends/skills/model_resolver.py.
Generic, zero-latency model resolution engine for skill-level model offloading.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from myrm_agent_harness.backends.skills.types import SkillMetadata

logger = logging.getLogger(__name__)


class SkillModelResolutionSource(StrEnum):
    """Source indicator for resolved skill execution model."""

    EXPLICIT_MODEL = "explicit_model"
    EXPLICIT_SKILL_MODEL = "explicit_model"
    TIER_MAPPING = "tier_mapping"
    AGENT_DEFAULT = "agent_default"
    FALLBACK = "fallback"


DEFAULT_TIER_MODELS: dict[str, str] = {
    "simple": "qwen-2.5-coder-1.5b",
    "standard": "claude-3-5-sonnet",
    "reasoning": "deepseek-reasoner",
}
DEFAULT_TIER_MAPPING: dict[str, str] = DEFAULT_TIER_MODELS


@dataclass(frozen=True, slots=True)
class SkillModelResolutionResult:
    """Result of resolving a specialized model for skill execution."""

    selected_model: str
    """The resolved model slug/identifier to use for skill execution."""

    model_tier: str | None
    """Recommended complexity tier ("simple", "standard", "reasoning", etc.)."""

    source: SkillModelResolutionSource
    """Where the model decision originated."""

    is_fallback: bool
    """Whether the resolution had to fall back due to unavailable requested model."""

    reason: str
    """Deterministic explanation of the resolution path."""

    declared_model: str | None = None
    """Original specialized_model declared in skill metadata."""

    declared_tier: str | None = None
    """Original model_tier declared in skill metadata."""

    @property
    def resolution_source(self) -> SkillModelResolutionSource:
        """Alias for source for backward compatibility."""
        return self.source

    def to_dict(self) -> dict[str, object]:
        """Serialize resolution result to standard dictionary."""
        return {
            "selected_model": self.selected_model,
            "model_tier": self.model_tier,
            "source": self.source.value,
            "is_fallback": self.is_fallback,
            "reason": self.reason,
            "declared_model": self.declared_model,
            "declared_tier": self.declared_tier,
        }


class SkillModelResolver:
    """Resolves declarative model requirements on skills to concrete runtime models."""

    @classmethod
    def resolve_model_for_skill(
        cls,
        skill: SkillMetadata,
        default_model: str = "claude-3-5-sonnet",
        available_models: set[str] | list[str] | None = None,
        tier_map: Mapping[str, str] | None = None,
    ) -> SkillModelResolutionResult:
        """Resolve model for skill using skill metadata."""
        return cls.resolve(
            skill_metadata=skill,
            default_model=default_model,
            available_models=available_models,
            tier_map=tier_map,
        )

    @classmethod
    def resolve_skill_model(
        cls,
        skill: SkillMetadata,
        default_model: str = "claude-3-5-sonnet",
        available_models: set[str] | list[str] | None = None,
        tier_map: Mapping[str, str] | None = None,
    ) -> SkillModelResolutionResult:
        """Alias for resolve_model_for_skill."""
        return cls.resolve_model_for_skill(
            skill=skill,
            default_model=default_model,
            available_models=available_models,
            tier_map=tier_map,
        )

    @classmethod
    def resolve(
        cls,
        skill_metadata: SkillMetadata,
        default_model: str = "claude-3-5-sonnet",
        available_models: set[str] | list[str] | None = None,
        tier_map: Mapping[str, str] | None = None,
    ) -> SkillModelResolutionResult:
        """Resolve the optimal model for a skill based on its metadata and environment.

        Resolution Priority:
        1. Explicit `specialized_model` in metadata if available in `available_models`.
        2. Mapped model from `model_tier` ("simple", "standard", "reasoning") if available.
        3. Fallback to `default_model`.
        """
        active_tier_map = dict(DEFAULT_TIER_MODELS)
        if tier_map:
            active_tier_map.update(tier_map)

        avail_set = set(available_models) if available_models is not None else None

        # 1. Try explicit specialized_model
        spec_model = skill_metadata.specialized_model
        declared_tier = skill_metadata.model_tier

        if spec_model:
            clean_spec = spec_model.strip()
            if avail_set is None or clean_spec in avail_set:
                return SkillModelResolutionResult(
                    selected_model=clean_spec,
                    model_tier=declared_tier,
                    source=SkillModelResolutionSource.EXPLICIT_SKILL_MODEL,
                    is_fallback=False,
                    reason=f"Used explicit specialized model '{clean_spec}' declared in skill metadata.",
                    declared_model=clean_spec,
                    declared_tier=declared_tier,
                )
            else:
                logger.warning(
                    "Skill '%s' requested specialized model '%s' which is not in available models.",
                    skill_metadata.name,
                    clean_spec,
                )

        # 2. Try declared model_tier
        if declared_tier:
            norm_tier = declared_tier.strip().lower()
            tier_candidate = active_tier_map.get(norm_tier)
            if tier_candidate and (avail_set is None or tier_candidate in avail_set):
                is_fb = spec_model is not None
                return SkillModelResolutionResult(
                    selected_model=tier_candidate,
                    model_tier=norm_tier,
                    source=SkillModelResolutionSource.TIER_MAPPING,
                    is_fallback=is_fb,
                    reason=(
                        f"Resolved model '{tier_candidate}' via model_tier='{norm_tier}'"
                        + (f" (fallback from unavailable '{spec_model}')" if is_fb else ".")
                    ),
                    declared_model=spec_model,
                    declared_tier=declared_tier,
                )

        # 3. Fallback to default model
        is_fb = spec_model is not None or declared_tier is not None
        return SkillModelResolutionResult(
            selected_model=default_model,
            model_tier=declared_tier,
            source=SkillModelResolutionSource.AGENT_DEFAULT if not is_fb else SkillModelResolutionSource.FALLBACK,
            is_fallback=is_fb,
            reason=(
                f"Defaulted to agent default model '{default_model}'"
                + (f" (fallback from requested model='{spec_model}', tier='{declared_tier}')" if is_fb else ".")
            ),
            declared_model=spec_model,
            declared_tier=declared_tier,
        )
