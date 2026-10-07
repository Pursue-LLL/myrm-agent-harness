"""Public facade of the persona router subsystem.

[INPUT]
- toolkits.memory.persona_router.gate::StyleSuppressionGate (POS: Gatekeeper inspecting user turn intent to
  strictly suppress persona tokens in technical tasks.)
- toolkits.memory.persona_router.router::AntiPollutionContextRouter (POS: Dynamic context router injecting
  persona facets strictly on demand and suppressing context pollution.)
- toolkits.memory.persona_router.types::PersonaFacet, PersonaRoutingDecision, TaskIntentCategory (POS: Typed
  data contracts for the persona router subsystem.)

[OUTPUT]
- Package facade re-exporting 5 public names: AntiPollutionContextRouter, PersonaFacet,
  PersonaRoutingDecision, StyleSuppressionGate, TaskIntentCategory

[POS]
Public facade of the persona router subsystem.
"""

from myrm_agent_harness.toolkits.memory.persona_router.gate import (
    StyleSuppressionGate,
)
from myrm_agent_harness.toolkits.memory.persona_router.router import (
    AntiPollutionContextRouter,
)
from myrm_agent_harness.toolkits.memory.persona_router.types import (
    PersonaFacet,
    PersonaRoutingDecision,
    TaskIntentCategory,
)

__all__ = [
    "AntiPollutionContextRouter",
    "PersonaFacet",
    "PersonaRoutingDecision",
    "StyleSuppressionGate",
    "TaskIntentCategory",
]
