"""[INPUT] External event triggers, matched policy rules, agent actions, and artifact modifications.
[OUTPUT] Public facade exporting event-driven causality lineage tracking and reverse file change attribution models.
[POS] myrm_agent_harness.observability.event_causality_lineage

Exposes:
- Models: ExternalEventTrigger, CausalityRuleMatch, AgentActionNode, ArtifactChangeRecord, CausalityLineageRecord, FileAttributionResult
- Tracker: EventCausalityTracker, get_default_event_causality_tracker
"""

from .models import (
    AgentActionNode,
    ArtifactChangeRecord,
    CausalityLineageRecord,
    CausalityRuleMatch,
    ExternalEventTrigger,
    FileAttributionResult,
)
from .tracker import (
    EventCausalityTracker,
    get_default_event_causality_tracker,
)

__all__ = [
    "AgentActionNode",
    "ArtifactChangeRecord",
    "CausalityLineageRecord",
    "CausalityRuleMatch",
    "EventCausalityTracker",
    "ExternalEventTrigger",
    "FileAttributionResult",
    "get_default_event_causality_tracker",
]
