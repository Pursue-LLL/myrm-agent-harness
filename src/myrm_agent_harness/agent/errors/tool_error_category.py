"""Canonical tool error categories for structured error classification.

Unifies all tool-related error_category strings into a single StrEnum.
StrEnum values match the frontend i18n keys (progressSteps.errorCategories.*),
ensuring backend classification and frontend display stay in sync.

[INPUT]
- (none)

[OUTPUT]
- ToolErrorCategory: Canonical error category for tool execution and guard errors.

[POS]
Canonical tool error categories for structured error classification.
"""

from __future__ import annotations

from enum import StrEnum


class ToolErrorCategory(StrEnum):
    """Canonical error category for tool execution and guard errors.

    Values are used as:
    1. error_category in ToolMessage.additional_kwargs
    2. SSE event error_category field
    3. Frontend i18n key: progressSteps.errorCategories.<value>
    """

    # --- Code execution errors (classify_execution_error) ---
    TIMEOUT = "timeout"
    OOM = "oom"
    NOT_FOUND = "not_found"
    SANDBOX_RO = "sandbox_ro"
    NETWORK_BLOCKED = "network_blocked"
    PERMISSION_DENIED = "permission_denied"
    SYNTAX = "syntax"
    IMPORT = "import"
    UNKNOWN = "unknown"

    # --- Guards layer (_tool_guards.py) ---
    HOOK_BLOCKED = "hook_blocked"
    ESTOP = "estop"
    LOOP_GUARD = "loop_guard"
    SANDBOX_BOUNDARY = "sandbox_boundary"
    FREQUENCY_GUARD = "frequency_guard"
    TURN_BUDGET_GUARD = "turn_budget_guard"
    STEERING = "steering"
    INVALID_TOOL = "invalid_tool"
    TRUST_ATTENUATION = "trust_attenuation"
    PII_GUARD = "pii_guard"
    CIRCUIT_BREAKER = "circuit_breaker"

    # --- Middleware / lifecycle ---
    CONTEXT_VALIDATION = "context_validation"
    POST_HOOK_BLOCKED = "post_hook_blocked"
    TOOL_CANCELLED = "tool_cancelled"
    GUARDRAIL_BLOCKED = "guardrail_blocked"

    # --- ExecutionResult post-classification ---
    OOM_KILLED = "oom_killed"
    EXECUTION_FAILURE = "execution_failure"
    SEGFAULT = "segfault"
    SIGNAL_TERMINATED = "signal_terminated"
    NONZERO_EXIT = "nonzero_exit"


__all__ = ["ToolErrorCategory"]
