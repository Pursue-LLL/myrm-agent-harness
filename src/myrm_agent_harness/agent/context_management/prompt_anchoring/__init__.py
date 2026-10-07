"""Package facade for prompt anchoring.

[INPUT]
- agent.context_management.prompt_anchoring.prompt_anchoring_types::AnchoredPromptBundle,
  EphemeralRuntimeMetadata, PrefixCacheDriftVerification, PromptLayerKind, StaticAnchorBlueprint (POS: Types
  and models for prompt anchoring.)
- agent.context_management.prompt_anchoring.system_prompt_anchoring_gateway::SystemPromptAnchoringGateway
  (POS: Gateway orchestrating dual-layer system prompt assembly and tail redirection.)

[OUTPUT]
- Re-exports: AnchoredPromptBundle, EphemeralRuntimeMetadata, PrefixCacheDriftVerification, PromptLayerKind,
  StaticAnchorBlueprint, SystemPromptAnchoringGateway

[POS]
Package facade for prompt anchoring.
"""

# ============================================================================
# System Prompt Static Prefix Anchoring & Tail Redirector Package (Item 168)
# ============================================================================

from .prompt_anchoring_types import (
    AnchoredPromptBundle,
    EphemeralRuntimeMetadata,
    PrefixCacheDriftVerification,
    PromptLayerKind,
    StaticAnchorBlueprint,
)
from .system_prompt_anchoring_gateway import SystemPromptAnchoringGateway

__all__ = [
    "AnchoredPromptBundle",
    "EphemeralRuntimeMetadata",
    "PrefixCacheDriftVerification",
    "PromptLayerKind",
    "StaticAnchorBlueprint",
    "SystemPromptAnchoringGateway",
]
