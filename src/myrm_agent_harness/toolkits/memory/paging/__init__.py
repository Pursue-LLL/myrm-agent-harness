"""Agent-Driven Memory Paging with Hard Boundary Governance.

Provides cursor-based active memory pagination, strict physical scope isolation,
and sliding-window token budget guards preventing runaway context consumption.
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
