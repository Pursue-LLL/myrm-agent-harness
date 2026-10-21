"""Conversational Multi-Specialist Summoning & Context Aggregation Module.

Exports domain models, specialist catalog definitions, and the
SpecialistSummoningCoordinator engine.

[INPUT]
- (none — 标准库与内建依赖)

[OUTPUT]
- (模块级副作用与注册)

[POS]
Conversational Multi-Specialist Summoning & Context Aggregation Module.
"""

from myrm_agent_harness.agent.sub_agents.specialist_summoning.summoner import (
    SpecialistSummoningCoordinator,
)
from myrm_agent_harness.agent.sub_agents.specialist_summoning.types import (
    AggregationCardType,
    SpecialistDomain,
    SpecialistProfile,
    StructuredAggregationCard,
    SummonExecutionStatus,
    SummonRequest,
    SummonSessionExecution,
    SummonTriggerSource,
)

__all__ = [
    "SpecialistSummoningCoordinator",
    "SpecialistDomain",
    "SpecialistProfile",
    "SummonTriggerSource",
    "AggregationCardType",
    "SummonExecutionStatus",
    "SummonRequest",
    "StructuredAggregationCard",
    "SummonSessionExecution",
]
