"""Completion guard subsystem — finish gate, verification, and deliverable checks."""

from myrm_agent_harness.agent.middlewares.completion.completion_guard import (
    CompletionGuard,
    classify_verification,
    is_mutating_tool,
    reset_completion_guard,
)
from myrm_agent_harness.agent.middlewares.completion.completion_guard_checklist import (
    build_checklist,
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
