# [INPUT]: None
# [OUTPUT]: DehydratedSummary, DynamicBudgetScaler, PostGenerationDehydrator, PromptDisciplineInjector, ResponseVerbosityLevel, ResponseVerbositySuite, TriTierResponseVerbosityControlAndDynamicDensityTunerSuite, VerbosityBudgetConfig, VerbosityContextBundle, VerbosityPreferenceResolver, VerbositySource
# [POS]: agent/context_management/response_verbosity/__init__.py

"""Tri-tier response verbosity control and dynamic density tuner package.

[INPUT]
- None (Package root exports).

[OUTPUT]
- DehydratedSummary: Structured concise summary extracted from post-generation verbose output.
- DynamicBudgetScaler: Scales physical token allowances and model hyper-parameters.
- PostGenerationDehydrator: Extracts ultra-concise executive digests and key takeaways.
- PromptDisciplineInjector: Generates precise prompt discipline directives for verbosity tiers.
- ResponseVerbosityLevel: Tri-tier density enum (LOW, MEDIUM, HIGH).
- ResponseVerbositySuite: Short-hand alias for developer convenience.
- TriTierResponseVerbosityControlAndDynamicDensityTunerSuite: Unified facade coordinating verbosity tuning.
- VerbosityBudgetConfig: Token budget limits and discipline constraints per tier.
- VerbosityContextBundle: Resolved verbosity decision bundle bound to a generation request.
- VerbosityPreferenceResolver: Hierarchically resolves effective tier from turn, session, profile, and system levels.
- VerbositySource: Origin of the resolved verbosity level in the cascade.

[POS]
Package entry point for Item 311 TriTierResponseVerbosityControlAndDynamicDensityTunerSuite.
"""

from .dynamic_budget_scaler import DynamicBudgetScaler
from .post_generation_dehydrator import PostGenerationDehydrator
from .prompt_discipline_injector import PromptDisciplineInjector
from .response_verbosity_suite import (
    ResponseVerbositySuite,
    TriTierResponseVerbosityControlAndDynamicDensityTunerSuite,
)
from .verbosity_preference_resolver import VerbosityPreferenceResolver
from .verbosity_types import (
    DehydratedSummary,
    ResponseVerbosityLevel,
    VerbosityBudgetConfig,
    VerbosityContextBundle,
    VerbositySource,
)

__all__ = [
    "DehydratedSummary",
    "DynamicBudgetScaler",
    "PostGenerationDehydrator",
    "PromptDisciplineInjector",
    "ResponseVerbosityLevel",
    "ResponseVerbositySuite",
    "TriTierResponseVerbosityControlAndDynamicDensityTunerSuite",
    "VerbosityBudgetConfig",
    "VerbosityContextBundle",
    "VerbosityPreferenceResolver",
    "VerbositySource",
]
