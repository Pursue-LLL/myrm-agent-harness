"""Subagent execution logic (aggregate root).

[INPUT]
- .executor_retry_mixin::SubagentExecutorRetryMixin (POS: Retry loop with workspace isolation, hooks, and graceful cancellation.)
- .executor_attempt_mixin::SubagentExecutorAttemptMixin (POS: One child-agent run attempt including fork context and result post-processing.)
- .executor_delegation_mixin::SubagentExecutorDelegationMixin (POS: Orchestrator-role child agents receive scoped delegation meta-tools.)
- .executor_helpers (POS: Pure helper functions for SubagentExecutor mixins and external callers.)

[OUTPUT]
- SubagentExecutor: child agent execution aggregate root
- Re-exported helper functions for tests and notifications

[POS]
Subagent executor aggregate root. MRO: Retry → Attempt → Delegation (locked by architecture tests).
Public import path: ``from ...executor import SubagentExecutor``.
"""

from .executor_delegation_mixin import SubagentExecutorDelegationMixin
from .executor_attempt_mixin import SubagentExecutorAttemptMixin
from .executor_helpers import (
    _auto_vault_or_truncate,
    _cascade_cancel_descendants,
    _compact_error_message,
    _estimate_msg_tokens,
    _filter_fork_messages,
    _parse_handover_state,
)
from .executor_retry_mixin import SubagentExecutorRetryMixin


class SubagentExecutor(
    SubagentExecutorRetryMixin,
    SubagentExecutorAttemptMixin,
    SubagentExecutorDelegationMixin,
):
    """Execute subagent with retry, workspace isolation, and event forwarding."""


__all__ = [
    "SubagentExecutor",
    "_auto_vault_or_truncate",
    "_cascade_cancel_descendants",
    "_compact_error_message",
    "_estimate_msg_tokens",
    "_filter_fork_messages",
    "_parse_handover_state",
]
