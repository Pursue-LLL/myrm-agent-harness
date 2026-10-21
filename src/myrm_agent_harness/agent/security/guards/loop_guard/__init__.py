"""Loop guard subsystem — unified inefficiency detection for Agent sessions.

[POS]
Detects looping/inefficient agent behaviors (repeated tool calls, no progress)
and emits verdicts to interrupt or redirect the session.

[INPUT]
- AgentPhase / 工具调用序列与会话阶段

[OUTPUT]
- LoopGuard: 循环守卫
- _stable_hash: 状态指纹哈希
- VERDICT_ALLOW 等裁决常量
"""

from .guard import LoopGuard, _stable_hash  # noqa: F401
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
    "VERDICT_ALLOW",
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
    "VerificationCategory",
    "WarningLevel",
    "get_tool_group",
]
