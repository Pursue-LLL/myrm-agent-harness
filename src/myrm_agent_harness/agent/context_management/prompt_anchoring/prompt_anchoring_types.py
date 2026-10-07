"""Types and models for prompt anchoring.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- PromptLayerKind: Classification of prompt layer for prefix cache stability.
- StaticAnchorBlueprint: Immutable Layer A specification: permanent static system guidelines.
- EphemeralRuntimeMetadata: Dynamic Layer B variables: timestamps, IDs, dynamic path and environment.
- AnchoredPromptBundle: Assembled dual-layer prompt bundle separating static prefix and ephemeral tail.
- PrefixCacheDriftVerification: Verification report proving static prefix invariance across execution turns.

[POS]
Types and models for prompt anchoring.
"""

# ============================================================================
# System Prompt Static Prefix Anchoring & Tail Redirector Contracts (Item 168)
# Strong typing contracts for dual-layer system prompt decoupling (Layer A static
# anchor vs Layer B ephemeral context tail redirect) and cache drift verification.
# ============================================================================

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class PromptLayerKind(str, Enum):
    """Classification of prompt layer for prefix cache stability."""

    STATIC_ANCHOR_LAYER_A = "static_anchor_layer_a"
    EPHEMERAL_TAIL_LAYER_B = "ephemeral_tail_layer_b"


@dataclass(frozen=True, slots=True)
class StaticAnchorBlueprint:
    """Immutable Layer A specification: permanent static system guidelines."""

    system_instructions: str
    safety_guidelines: str
    tool_protocols: str
    domain_knowledge: str = ""


@dataclass(frozen=True, slots=True)
class EphemeralRuntimeMetadata:
    """Dynamic Layer B variables: timestamps, IDs, dynamic path and environment."""

    timestamp_iso: str
    timezone_name: str
    session_id: str
    workspace_cwd: str
    additional_variables: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AnchoredPromptBundle:
    """Assembled dual-layer prompt bundle separating static prefix and ephemeral tail."""

    layer_a_static_prefix: str
    layer_a_sha256: str
    layer_b_tail_injection: str
    layer_b_sha256: str
    combined_system_prompt: str
    redirect_to_user_message: bool
    prefix_tokens_estimate: int
    created_at_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(frozen=True, slots=True)
class PrefixCacheDriftVerification:
    """Verification report proving static prefix invariance across execution turns."""

    is_prefix_stable: bool
    layer_a_prefix_hash: str
    drift_detected_in_static: bool
    ephemeral_tail_changed: bool
    diagnostic_notes: str
