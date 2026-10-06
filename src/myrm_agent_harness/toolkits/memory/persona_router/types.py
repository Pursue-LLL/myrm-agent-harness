# [POS] src/myrm_agent_harness/toolkits/memory/persona_router/types.py
# [INPUT] enum, dataclasses, typing
# [OUTPUT] TaskIntentCategory, PersonaFacet, PersonaRoutingDecision

from dataclasses import dataclass, field
from enum import StrEnum


class TaskIntentCategory(StrEnum):
    """Categorized operational intent for contextual persona gating."""

    TECHNICAL_EXECUTION = "technical_execution"
    CREATIVE_COMMUNICATION = "creative_communication"
    GENERAL_QUERY = "general_query"


@dataclass(frozen=True)
class PersonaFacet:
    """Decoupled user identity and style preference facet acting as an on-demand skill."""

    facet_id: str
    name: str
    tone_guidance: str
    sample_excerpts: tuple[str, ...] = field(default_factory=tuple)
    target_intents: tuple[str, ...] = field(default_factory=tuple)
    is_default: bool = False
    estimated_tokens: int = 150


@dataclass(frozen=True)
class PersonaRoutingDecision:
    """Outcome of intent-aware persona style suppression and selective injection routing."""

    is_suppressed: bool
    intent_category: TaskIntentCategory
    active_facets: tuple[str, ...]
    injected_content: str
    tokens_saved_estimate: int
    decision_reason: str
