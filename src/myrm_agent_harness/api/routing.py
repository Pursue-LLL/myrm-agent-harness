"""Public LLM routing API surface.

[INPUT]
- toolkits.llms.routing.complexity_router::RoutingResult, RoutingTier, route_task
- toolkits.llms.routing.specialty_router::SpecialtyRoutingResult, TaskSpecialty, classify_task_specialty, route_task_specialty

[OUTPUT]
- RoutingResult, RoutingTier, route_task
- SpecialtyRoutingResult, TaskSpecialty, classify_task_specialty, route_task_specialty

[POS]
Top-level API routing facade for task complexity and model specialty dispatching.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.llms.routing.complexity_router import (
    RoutingResult,
    RoutingTier,
    route_task,
)
from myrm_agent_harness.toolkits.llms.routing.specialty_router import (
    SpecialtyRoutingResult,
    TaskSpecialty,
    classify_task_specialty,
    route_task_specialty,
)

__all__ = [
    "RoutingResult",
    "RoutingTier",
    "SpecialtyRoutingResult",
    "TaskSpecialty",
    "classify_task_specialty",
    "route_task",
    "route_task_specialty",
]
