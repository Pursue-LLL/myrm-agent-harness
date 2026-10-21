"""One-Model Multi-Agent Shared Context Token Budget Governance Package.

Provides shared primary model token ceilings, per-role budget allocation,
fan-out precheck, and routing overhead vs execution payload Doctor alerts.

[INPUT]
- (none — 标准库与内建依赖)

[OUTPUT]
- (模块级副作用与注册)

[POS]
One-Model Multi-Agent Shared Context Token Budget Governance Package.
"""

from myrm_agent_harness.agent.sub_agents.token_budget_governance.governor import (
    SharedTokenBudgetGovernor,
)
from myrm_agent_harness.agent.sub_agents.token_budget_governance.types import (
    BudgetExceededError,
    ConsumptionCategory,
    ConsumptionRecord,
    DoctorNudgeAlert,
    GovernancePrecheckResult,
    NudgeSeverity,
    RoleBudgetNotFoundError,
    RoleBudgetSpec,
    SharedTokenBudgetSnapshot,
    TokenBudgetError,
)

__all__ = [
    "SharedTokenBudgetGovernor",
    "RoleBudgetSpec",
    "ConsumptionRecord",
    "ConsumptionCategory",
    "NudgeSeverity",
    "GovernancePrecheckResult",
    "DoctorNudgeAlert",
    "SharedTokenBudgetSnapshot",
    "TokenBudgetError",
    "BudgetExceededError",
    "RoleBudgetNotFoundError",
]
