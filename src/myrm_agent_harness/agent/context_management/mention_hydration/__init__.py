"""Package facade for GUI-first @-mention zero-turn context hydration.

[INPUT]
- agent.context_management.mention_hydration.mention_hydration_engine::MentionHydrationEngine,
  compute_content_hash (POS: Main engine transforming @-mention references into transparent pre-hydrated
  context attachments.)
- agent.context_management.mention_hydration.mention_hydration_types::HydratedTurnPayload,
  MentionHydrationConfig, MentionKind, PreHydratedAttachment (POS: Data contracts for zero-turn @-mention
  extraction, deduplication, and context injection.)
- agent.context_management.mention_hydration.mention_parser::ParsedMention, parse_mentions_from_prompt (POS:
  Extracts structured @-mention entities from raw prompt text while avoiding false positives like email
  addresses.)

[OUTPUT]
- Re-exports: HydratedTurnPayload, MentionHydrationConfig, MentionHydrationEngine, MentionKind, ParsedMention,
  PreHydratedAttachment, compute_content_hash, parse_mentions_from_prompt

[POS]
GUI-first @-mention zero-turn context hydration facade.
"""

from __future__ import annotations

from .mention_hydration_engine import (
    MentionHydrationEngine,
    compute_content_hash,
)
from .mention_hydration_types import (
    HydratedTurnPayload,
    MentionHydrationConfig,
    MentionKind,
    PreHydratedAttachment,
)
from .mention_parser import (
    ParsedMention,
    parse_mentions_from_prompt,
)

__all__ = [
    "HydratedTurnPayload",
    "MentionHydrationConfig",
    "MentionHydrationEngine",
    "MentionKind",
    "ParsedMention",
    "PreHydratedAttachment",
    "compute_content_hash",
    "parse_mentions_from_prompt",
]
