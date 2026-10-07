"""Agent-Driven Memory Paging with Hard Boundary Governance.

Provides cursor-based active memory pagination, strict physical scope isolation,
and sliding-window token budget guards preventing runaway context consumption.

[INPUT]
- toolkits.memory.paging.engine::AgentMemoryPagingEngine (POS: Agent-Driven Memory Paging Engine with cursor
  pagination and token budget guards.)
- toolkits.memory.paging.gateway::HardBoundaryScopeGateway (POS: Hard Boundary Scope Gateway enforcing
  physical multi-tenant and project isolation.)
- toolkits.memory.paging.models::AccessViolationAudit, AccessViolationError, HardScopeContext,
  MemoryPageQuery, MemoryPageRecord, MemoryPageResult, PagingBudgetExceededError, PagingBudgetPolicy (POS:
  Data models for Agent-Driven Memory Paging and Hard Boundary Governance Engine.)

[OUTPUT]
- Package facade re-exporting 10 public names: AccessViolationAudit, AccessViolationError,
  AgentMemoryPagingEngine, HardBoundaryScopeGateway, HardScopeContext, MemoryPageQuery, MemoryPageRecord,
  MemoryPageResult, PagingBudgetExceededError, PagingBudgetPolicy

[POS]
Agent-Driven Memory Paging with Hard Boundary Governance.
"""

from .engine import AgentMemoryPagingEngine
from .gateway import HardBoundaryScopeGateway
from .models import (
    AccessViolationAudit,
    AccessViolationError,
    HardScopeContext,
    MemoryPageQuery,
    MemoryPageRecord,
    MemoryPageResult,
    PagingBudgetExceededError,
    PagingBudgetPolicy,
)

__all__ = [
    "AccessViolationAudit",
    "AccessViolationError",
    "AgentMemoryPagingEngine",
    "HardBoundaryScopeGateway",
    "HardScopeContext",
    "MemoryPageQuery",
    "MemoryPageRecord",
    "MemoryPageResult",
    "PagingBudgetExceededError",
    "PagingBudgetPolicy",
]
