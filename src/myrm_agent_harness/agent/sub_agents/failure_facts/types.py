"""[INPUT] None.
[OUTPUT] Enum types and data contracts for Subagent Bounded Structured Failure Facts & Safe Diagnostic Protocol.
[POS] Core schema layer for privacy-preserving subagent error categorization and single-line diagnostic header generation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class SubagentFailureStage(StrEnum):
    """Subagent execution lifecycle stages where failures can originate."""

    QUERY_START = "query-start"
    THREAD_START = "thread-start"
    TURN_START = "turn-start"
    TURN = "turn"
    PROCESS = "process"
    TEARDOWN = "teardown"


class SubagentFailureCategory(StrEnum):
    """Precise, machine-actionable error categorization."""

    CONTEXT_WINDOW_EXCEEDED = "contextWindowExceeded"
    SESSION_BUDGET_EXCEEDED = "sessionBudgetExceeded"
    SANDBOX_ERROR = "sandboxError"
    ERROR_MAX_TURNS = "error_max_turns"
    RATE_LIMITED = "rateLimited"
    AUTH_ERROR = "authError"
    NETWORK_TIMEOUT = "networkTimeout"
    PROCESS_ABORTED = "processAborted"
    UNKNOWN_FAILURE = "unknownFailure"


class RemediationAction(StrEnum):
    """Deterministic guidance for parent agent self-healing and recovery."""

    COMPACT_AND_RESUME = "compact_and_resume"
    RETRY_WITH_BACKOFF = "retry_with_backoff"
    RETRY_ONCE = "retry_once"
    ABORT_EARLY = "abort_early"
    ESCALATE_TO_USER = "escalate_to_user"
    RESPAWN_CLEAN_SANDBOX = "respawn_clean_sandbox"
    SYNTHESIZE_PARTIAL_FINDINGS = "synthesize_partial_findings"


@dataclass(frozen=True)
class StructuredFailureFact:
    """Bounded, privacy-sanitized structured subagent failure fact."""

    product: str
    stage: SubagentFailureStage
    category: SubagentFailureCategory
    http_status: int | None = None
    exit_code: int | None = None
    signal: str | None = None
    sanitized_message: str = ""
    remediation: RemediationAction = RemediationAction.RETRY_WITH_BACKOFF
    safe_diagnostic_header: str = ""
    byte_size: int = 0
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, str] = field(default_factory=dict)
