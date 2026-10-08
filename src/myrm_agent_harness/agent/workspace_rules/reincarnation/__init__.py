# [INPUT]: None
# [OUTPUT]: CrashCause, HeritageHydrationResult, HeritageSafetyFilterGate, HeritageTabooLesson, InstantHeritageHydrator, ReincarnationCircuitBreaker, ReincarnationDossier, ReincarnationEvent, ReincarnationNamespaceAndAgentHeritageInheritanceProtocolSuite, ReincarnationProtocolSuite, SoulLineageRecord, UnfinishedGoal, WorkingHabitShortcut
# [POS]: agent/workspace_rules/reincarnation/__init__.py

"""Agent reincarnation namespace and heritage inheritance protocol package.

[INPUT]
- None (Package root exports).

[OUTPUT]
- CrashCause: Primary causes precipitating agent reincarnation.
- HeritageHydrationResult: Outcome of injecting heritage into session prompt.
- HeritageSafetyFilterGate: Screen speculative hypotheses and enforce 2000-char budget.
- HeritageTabooLesson: Hard-learned lessons, user rebukes, and strict boundaries.
- InstantHeritageHydrator: Detects, injects, and auto-archives REINCARNATION.md.
- ReincarnationCircuitBreaker: Intercepts catastrophic context snowball/crashes and distills clean heritage.
- ReincarnationDossier: Aggregated 4-section heritage package strictly bounded to 2000 chars.
- ReincarnationEvent: Metadata receipt describing the reincarnation occurrence.
- ReincarnationNamespaceAndAgentHeritageInheritanceProtocolSuite: Unified facade for Item 315.
- ReincarnationProtocolSuite: Convenient alias.
- SoulLineageRecord: Generation number, predecessor/successor models, and cumulative pedigree.
- UnfinishedGoal: Pending long-horizon objectives inherited across generations.
- WorkingHabitShortcut: User-specific shortcuts, shorthand slang, and preferred paths.

[POS]
Package entry point for Item 315 ReincarnationNamespaceAndAgentHeritageInheritanceProtocolSuite.
"""

from .heritage_safety_filter_gate import HeritageSafetyFilterGate
from .instant_heritage_hydrator import InstantHeritageHydrator
from .reincarnation_circuit_breaker import ReincarnationCircuitBreaker
from .reincarnation_protocol_suite import (
    ReincarnationNamespaceAndAgentHeritageInheritanceProtocolSuite,
    ReincarnationProtocolSuite,
)
from .reincarnation_types import (
    CrashCause,
    HeritageHydrationResult,
    HeritageTabooLesson,
    ReincarnationDossier,
    ReincarnationEvent,
    SoulLineageRecord,
    UnfinishedGoal,
    WorkingHabitShortcut,
)

__all__ = [
    "CrashCause",
    "HeritageHydrationResult",
    "HeritageSafetyFilterGate",
    "HeritageTabooLesson",
    "InstantHeritageHydrator",
    "ReincarnationCircuitBreaker",
    "ReincarnationDossier",
    "ReincarnationEvent",
    "ReincarnationNamespaceAndAgentHeritageInheritanceProtocolSuite",
    "ReincarnationProtocolSuite",
    "SoulLineageRecord",
    "UnfinishedGoal",
    "WorkingHabitShortcut",
]
