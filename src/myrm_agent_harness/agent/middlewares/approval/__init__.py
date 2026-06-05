"""Tool approval subsystem — Human-in-the-Loop approval flow.

Provides batch tool-call approval via LangGraph interrupt() mechanism,
with rate limiting, denial tracking, allowlist management, and optional
LLM-based security review (Layer 4.5).

Components:
- middleware: ToolApprovalMiddleware (after_model hook orchestrator)
- batch_processor: Batch evaluation, interrupt payload construction, decision application
- helpers: Denial counter, allowlist helpers
- rate_limiter: Sliding-window rate limiter for approval requests
"""

from myrm_agent_harness.agent.middlewares._session_context import (
    get_event_logger,
    set_agent_id,
    set_approval_session,
    set_approval_user_id,
    set_event_logger,
    set_security_config,
    set_workspace_root,
)
from myrm_agent_harness.agent.middlewares.approval.batch_processor import register_security_reviewer
from myrm_agent_harness.agent.middlewares.approval.helpers import (
    ThresholdBreach,
    add_to_allowlist_if_needed,
    is_threshold_breached,
    record_approval,
    record_denial,
    reset_denial_counter,
)
from myrm_agent_harness.agent.middlewares.approval.middleware import ToolApprovalMiddleware
from myrm_agent_harness.agent.middlewares.approval.rate_limiter import ApprovalRateLimiter, get_approval_rate_limiter

__all__ = [
    "ApprovalRateLimiter",
    "ThresholdBreach",
    "ToolApprovalMiddleware",
    "add_to_allowlist_if_needed",
    "get_approval_rate_limiter",
    "get_event_logger",
    "is_threshold_breached",
    "record_approval",
    "record_denial",
    "register_security_reviewer",
    "reset_denial_counter",
    "set_agent_id",
    "set_approval_session",
    "set_approval_user_id",
    "set_event_logger",
    "set_security_config",
    "set_workspace_root",
]
