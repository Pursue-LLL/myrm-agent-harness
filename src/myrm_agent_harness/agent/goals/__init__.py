"""Goal engine exports.

[INPUT]
- .types::Goal, GoalStatus, GoalBudget, GoalAccountingOutcome, ContinuationDecision (POS: Goal data types)
- .protocol::GoalProvider (POS: GoalProvider protocol)
- .manager::GoalManager (POS: GoalManager implementation)
- .continuation::check_continuation (POS: Continuation guard chain)

[OUTPUT]
- Exports for the Goal engine.

[POS]
Package entry point for the Goal engine.
"""

from .continuation import check_continuation
from .manager import GoalManager
from .protocols import GoalProvider
from .types import ContinuationDecision, Goal, GoalAccountingOutcome, GoalBudget, GoalStatus

__all__ = [
    "ContinuationDecision",
    "Goal",
    "GoalAccountingOutcome",
    "GoalBudget",
    "GoalManager",
    "GoalProvider",
    "GoalStatus",
    "check_continuation",
]
