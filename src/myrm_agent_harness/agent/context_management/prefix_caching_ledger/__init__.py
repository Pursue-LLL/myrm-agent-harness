"""Prefix-caching aligned context layout and hidden reasoning token ledger package.

[INPUT]
- None (Package root exports).

[OUTPUT]
- ContextBlockDescriptor: Atomic context block annotated with tier and category.
- ContextTier: Three-tier classification (TIER1_STATIC_PREFIX, TIER2_SEMI_STATIC_PROJECT, TIER3_DYNAMIC_TAIL).
- HiddenReasoningTokensPenetrationAuditor: Penetration auditor resolving hidden reasoning and cache tokens.
- MultiDimensionalSessionTokenLedger: Session-scoped multi-turn token and savings ledger.
- PrefixCachingAlignedContextLayoutAndHiddenReasoningTokenLedgerSuite: Unified facade coordinating layout and ledger.
- PrefixCachingAlignedLayoutEngine: Deterministic three-tier layout assembler.
- PrefixCachingLayoutConfig: Configuration for ordering, clock placement, and discounts.
- TokenUsageBreakdown: Audited multi-dimensional token usage breakdown.
- TurnLedgerRecord: Snapshot of a single turn's token metrics.

[POS]
Package entry point for prefix-caching optimization and penetrating usage accounting.
"""

from .hidden_reasoning_tokens_penetration_auditor import (
    HiddenReasoningTokensPenetrationAuditor,
)
from .multi_dimensional_session_token_ledger import MultiDimensionalSessionTokenLedger
from .prefix_caching_aligned_context_layout_and_hidden_reasoning_token_ledger_suite import (
    PrefixCachingAlignedContextLayoutAndHiddenReasoningTokenLedgerSuite,
)
from .prefix_caching_aligned_layout_engine import PrefixCachingAlignedLayoutEngine
from .prefix_caching_types import (
    ContextBlockDescriptor,
    ContextTier,
    PrefixCachingLayoutConfig,
    TokenUsageBreakdown,
    TurnLedgerRecord,
)

__all__ = [
    "ContextBlockDescriptor",
    "ContextTier",
    "HiddenReasoningTokensPenetrationAuditor",
    "MultiDimensionalSessionTokenLedger",
    "PrefixCachingAlignedContextLayoutAndHiddenReasoningTokenLedgerSuite",
    "PrefixCachingAlignedLayoutEngine",
    "PrefixCachingLayoutConfig",
    "TokenUsageBreakdown",
    "TurnLedgerRecord",
]
