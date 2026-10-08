# [INPUT]: DehydratedSummary, DynamicBudgetScaler, PostGenerationDehydrator, PromptDisciplineInjector, ResponseVerbosityLevel, VerbosityBudgetConfig, VerbosityContextBundle, VerbosityPreferenceResolver, VerbositySource
# [OUTPUT]: ResponseVerbositySuite, TriTierResponseVerbosityControlAndDynamicDensityTunerSuite
# [POS]: agent/context_management/response_verbosity/response_verbosity_suite.py

"""Comprehensive facade suite for tri-tier response verbosity and dynamic density tuning.

[INPUT]
- ResponseVerbosityLevel, VerbosityBudgetConfig, VerbosityContextBundle, DehydratedSummary: Contract models.
- VerbosityPreferenceResolver, PromptDisciplineInjector, DynamicBudgetScaler, PostGenerationDehydrator: Underlying components.

[OUTPUT]
- TriTierResponseVerbosityControlAndDynamicDensityTunerSuite: Primary facade for Item 311.
- ResponseVerbositySuite: Convenient alias.

[POS]
Main entry point coordinating preference resolution, discipline injection, token scaling, and post-generation TL;DR.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .dynamic_budget_scaler import DynamicBudgetScaler
from .post_generation_dehydrator import PostGenerationDehydrator
from .prompt_discipline_injector import PromptDisciplineInjector
from .verbosity_preference_resolver import VerbosityPreferenceResolver
from .verbosity_types import (
    DehydratedSummary,
    ResponseVerbosityLevel,
    VerbosityBudgetConfig,
    VerbosityContextBundle,
    VerbositySource,
)


class TriTierResponseVerbosityControlAndDynamicDensityTunerSuite:
    """Unified facade managing tri-tier verbosity levels, dynamic token caps, and concise post-digests."""

    def __init__(self, config: VerbosityBudgetConfig | None = None) -> None:
        self._config = config or VerbosityBudgetConfig()
        self._resolver = VerbosityPreferenceResolver(self._config)
        self._injector = PromptDisciplineInjector()
        self._scaler = DynamicBudgetScaler(self._config)
        self._dehydrator = PostGenerationDehydrator()

    @property
    def config(self) -> VerbosityBudgetConfig:
        """The configuration in effect."""
        return self._config

    def resolve_and_bind(
        self,
        turn_override: ResponseVerbosityLevel | str | None = None,
        session_preference: ResponseVerbosityLevel | str | None = None,
        profile_default: ResponseVerbosityLevel | str | None = None,
        model_hard_ceiling: int | None = None,
    ) -> VerbosityContextBundle:
        """Resolve effective verbosity tier and produce a fully bound execution context bundle."""
        resolved_level, source = self._resolver.resolve(
            turn_override=turn_override,
            session_preference=session_preference,
            profile_default=profile_default,
        )

        discipline_instruction = ""
        if self._config.inject_system_discipline_prompt:
            discipline_instruction = self._injector.generate_discipline_instruction(resolved_level)

        max_tokens, presence_penalty = self._scaler.scale_budget(
            level=resolved_level,
            model_hard_ceiling=model_hard_ceiling,
        )

        return VerbosityContextBundle(
            level=resolved_level,
            source=source,
            prompt_discipline_instruction=discipline_instruction,
            recommended_max_tokens=max_tokens,
            recommended_presence_penalty=presence_penalty,
        )

    def dehydrate_response(self, text: str, max_takeaways: int = 3) -> DehydratedSummary:
        """Extract a structured, ultra-concise TL;DR executive digest from a verbose response."""
        return self._dehydrator.dehydrate(text, max_takeaways=max_takeaways)

    def get_composer_segmented_options(self) -> Sequence[Mapping[str, str]]:
        """Return UI metadata describing each verbosity option for frontend segmented pills."""
        return (
            {
                "id": ResponseVerbosityLevel.LOW.value,
                "label": "⚡ 极简",
                "tooltip": "直给结论与代码，严禁客套寒暄，限制输出长度，降低延迟",
                "max_tokens": str(self._config.low_max_tokens),
            },
            {
                "id": ResponseVerbosityLevel.MEDIUM.value,
                "label": "⚖️ 均衡",
                "tooltip": "标准工程答复，涵盖要点与必要原因",
                "max_tokens": str(self._config.medium_max_tokens),
            },
            {
                "id": ResponseVerbosityLevel.HIGH.value,
                "label": "📖 详尽",
                "tooltip": "深度展开推演脉络、架构权衡与详细代码注释",
                "max_tokens": str(self._config.high_max_tokens),
            },
        )


ResponseVerbositySuite = TriTierResponseVerbosityControlAndDynamicDensityTunerSuite
