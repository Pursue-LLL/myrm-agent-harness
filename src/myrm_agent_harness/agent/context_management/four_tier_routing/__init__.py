# [INPUT]: None
# [OUTPUT]: AssembledContextPayload, ContextTierKind, FourTierContextConfig, FourTierContextRoutingAndSynthesisEngineSuite, JitHandle, JitRetrievalProtocol, KnowledgeSynthesisEngine, SynthesisInput, SynthesizedDirective, TriggerDomainKind, TriggeredContextRouter, TriggeredRule
# [POS]: agent/context_management/four_tier_routing/__init__.py

"""Four-Tier Context Engineering Architecture package.

[INPUT]
- None (Public package entrypoint).

[OUTPUT]
- AssembledContextPayload: Container for multi-tier context output.
- ContextTierKind: The four distinct architectural tiers.
- FourTierContextConfig: Configuration for thresholds and formatting.
- FourTierContextRoutingAndSynthesisEngineSuite: Central facade suite.
- JitHandle: Lightweight on-demand reference pointer.
- JitRetrievalProtocol: JIT handle registration and hydration manager.
- KnowledgeSynthesisEngine: Pre-prompt multi-source knowledge synthesizer.
- SynthesisInput: Bundle of fragments, ADRs, and postmortems.
- SynthesizedDirective: Actionable engineering judgment model.
- TriggerDomainKind: Specialized operation domains.
- TriggeredContextRouter: Dynamic domain rule router.
- TriggeredRule: Triggered domain discipline specification.

[POS]
Package facade for Anthropic Context Engineering inspired four-tier context assembly.
"""

from __future__ import annotations

from .four_tier_context_suite import (
    FourTierContextRoutingAndSynthesisEngineSuite,
)
from .four_tier_types import (
    AssembledContextPayload,
    ContextTierKind,
    FourTierContextConfig,
    JitHandle,
    SynthesisInput,
    SynthesizedDirective,
    TriggerDomainKind,
    TriggeredRule,
)
from .jit_retrieval_protocol import JitRetrievalProtocol
from .knowledge_synthesis_engine import KnowledgeSynthesisEngine
from .triggered_context_router import TriggeredContextRouter

__all__ = [
    "AssembledContextPayload",
    "ContextTierKind",
    "FourTierContextConfig",
    "FourTierContextRoutingAndSynthesisEngineSuite",
    "JitHandle",
    "JitRetrievalProtocol",
    "KnowledgeSynthesisEngine",
    "SynthesisInput",
    "SynthesizedDirective",
    "TriggerDomainKind",
    "TriggeredContextRouter",
    "TriggeredRule",
]
