"""Loop guard subsystem — unified inefficiency detection for Agent sessions.

Re-exports the public API so callers can use
``from ...guards.loop_guard import LoopGuard`` as before.
"""

from .guard import LoopGuard, _stable_hash
from .types import (
    VERDICT_ALLOW,
    AgentPhase,
    CallRecord,
    ErrorPattern,
    LoopAction,
    LoopGuardMetrics,
    LoopKind,
    LoopVerdict,
    SuccessLevel,
    SuggestionPriority,
    ToolGroup,
    VerificationCategory,
    WarningLevel,
    get_tool_group,
)

__all__ = [
    "AgentPhase",
    "CallRecord",
    "ErrorPattern",
    "LoopAction",
    "LoopGuard",
    "LoopGuardMetrics",
    "LoopKind",
    "LoopVerdict",
    "SuccessLevel",
    "SuggestionPriority",
    "ToolGroup",
    "VERDICT_ALLOW",
    "VerificationCategory",
    "WarningLevel",
    "get_tool_group",
]
