"""Subagent execution logic (aggregate root).

[INPUT]
- executor_retry_mixin, executor_attempt_mixin, executor_delegation_mixin (POS: split executor mixins)
- executor_helpers (POS: pure helper functions)

[OUTPUT]
- SubagentExecutor: child agent execution aggregate root
- Re-exported helper functions for tests and notifications

[POS]
Subagent executor aggregate. MRO: Retry → Attempt → Delegation (locked by architecture tests).
Public import path unchanged: ``from ...executor import SubagentExecutor``.
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
