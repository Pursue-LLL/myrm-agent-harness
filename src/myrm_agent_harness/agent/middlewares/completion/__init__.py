"""Completion guard subsystem — finish gate, verification, and deliverable checks.

[INPUT]
- 会话轨迹 / AgentRunStatistics（运行统计）

[OUTPUT]
- CompletionGuard: 完成判定守卫
- build_checklist(): 交付清单构建
- classify_verification(): 验证结果分类

[POS]
Finish-gate subsystem ensuring the agent only reports completion after
verification and deliverable checks pass.
"""

from myrm_agent_harness.agent.middlewares.completion.completion_guard import (
    CompletionGuard,
    classify_verification,
    reset_completion_guard,
)
from myrm_agent_harness.agent.middlewares.completion.completion_guard_checklist import (
    build_checklist,
)
from myrm_agent_harness.agent.middlewares.completion.completion_guard_safety import (
    is_mutating_tool,
)
from myrm_agent_harness.agent.middlewares.completion.deliverable_write_verifier import (
    check_deliverable_write_claim,
)
from myrm_agent_harness.agent.orchestration.hooks import COMPLETION_CHECK_TOOL_NAME

__all__ = [
    "COMPLETION_CHECK_TOOL_NAME",
    "CompletionGuard",
    "build_checklist",
    "check_deliverable_write_claim",
    "classify_verification",
    "is_mutating_tool",
    "reset_completion_guard",
]
