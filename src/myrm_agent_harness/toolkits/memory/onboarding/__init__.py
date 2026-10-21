"""Onboarding insight sampling and first-encounter report toolkit package.

[INPUT]
- .models: OnboardingSampleOptions, SampledTurnMessage, OnboardingConversationWindow, InsightExtractedFact, FirstEncounterReport
- .entropy_inspector: ShannonEntropyInspector
- .redactor: LocalSecretRedactor
- .adapters: BaseAgentSourceAdapter, CursorSourceAdapter, ClaudeCodeSourceAdapter, CodexSourceAdapter, HermesSourceAdapter, OpenClawSourceAdapter
- .registry: OnboardingSourceRegistry
- .sampler: MultiSourceOnboardingSampler
- .distiller: OnboardingInsightDistiller

[OUTPUT]
- Public symbols exported for framework callers and memory pipeline.

[POS]
Harness framework top-level facade for onboarding insight sampling and reporting.
"""

from __future__ import annotations

from .adapters import (
    BaseAgentSourceAdapter,
    ClaudeCodeSourceAdapter,
    CodexSourceAdapter,
    CursorSourceAdapter,
    HermesSourceAdapter,
    OpenClawSourceAdapter,
)
from .distiller import OnboardingInsightDistiller
from .entropy_inspector import ShannonEntropyInspector
from .models import (
    FirstEncounterReport,
    InsightExtractedFact,
    OnboardingConversationWindow,
    OnboardingSampleOptions,
    SampledTurnMessage,
)
from .redactor import LocalSecretRedactor
from .registry import OnboardingSourceRegistry
from .sampler import MultiSourceOnboardingSampler

__all__ = [
    "BaseAgentSourceAdapter",
    "ClaudeCodeSourceAdapter",
    "CodexSourceAdapter",
    "CursorSourceAdapter",
    "FirstEncounterReport",
    "HermesSourceAdapter",
    "InsightExtractedFact",
    "LocalSecretRedactor",
    "MultiSourceOnboardingSampler",
    "OnboardingConversationWindow",
    "OnboardingInsightDistiller",
    "OnboardingSampleOptions",
    "OnboardingSourceRegistry",
    "OpenClawSourceAdapter",
    "SampledTurnMessage",
    "ShannonEntropyInspector",
]
