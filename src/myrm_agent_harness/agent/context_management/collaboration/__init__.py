"""Package facade for collaboration.

[INPUT]
- agent.context_management.collaboration.collaboration_types::ArtifactInlineAnnotation, SanitizedMessage,
  ShareAccessLevel, SharedSessionSnapshot, SharedSessionToken, SteeringDirective (POS: Types and models for
  collaboration.)
- agent.context_management.collaboration.shared_session_hub::SharedCloudSessionHub (POS: Manages shared cloud
  session snapshots, security gates, and team steering.)

[OUTPUT]
- Re-exports: ArtifactInlineAnnotation, SanitizedMessage, ShareAccessLevel, SharedCloudSessionHub,
  SharedSessionSnapshot, SharedSessionToken, SteeringDirective

[POS]
Package facade for collaboration.
"""

# ============================================================================
# Shared Cloud Session & Collaboration Subpackage (Item 153)
# ============================================================================

from .collaboration_types import (
    ArtifactInlineAnnotation,
    SanitizedMessage,
    ShareAccessLevel,
    SharedSessionSnapshot,
    SharedSessionToken,
    SteeringDirective,
)
from .shared_session_hub import SharedCloudSessionHub

__all__ = [
    "ArtifactInlineAnnotation",
    "SanitizedMessage",
    "ShareAccessLevel",
    "SharedCloudSessionHub",
    "SharedSessionSnapshot",
    "SharedSessionToken",
    "SteeringDirective",
]
