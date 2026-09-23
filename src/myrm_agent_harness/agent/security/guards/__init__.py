"""Security guards for the Agent runtime.

Available guards:
- loop_guard: Detects logical loops (repetition, ping-pong, no-progress, divergence)
- frequency_guard: Detects time-based call frequency anomalies (DoS prevention)
- tool_turn_budget_guard: Per-user-turn call budget for high-cost tools (e.g. web_search)
- negative_constraint_guard: Enforces VETO rules and redlines before tool execution
- taint_tracker: Tracks information flow labels (prompt→command injection prevention)
- estop: Global emergency stop mechanism
- context_budget: Context window size management
- privacy_tracker: PII and privacy tracking
- ssrf_guard: SSRF protection for network tools

[POS]
Session-level security guards integrated into tool_interceptor_middleware.
Each guard is an independent module; the middleware orchestrates execution order.
"""

from .negative_constraint_guard import (
    NegativeConstraint,
    NegativeConstraintComplianceGate,
    NegativeConstraintVerdict,
    VetoAction,
    get_compliance_gate,
    reset_compliance_gate,
)
from .taint_tracker import (
    TaintLabel,
    TaintTracker,
    get_taint_tracker,
    reset_taint_tracker,
)
from .untrusted_ingress_fence import (
    DISALLOWED_UNTRUSTED_PERMISSIONS,
    DISALLOWED_UNTRUSTED_TOOLS,
    filter_untrusted_ingress_tools,
    is_tool_allowed_under_untrusted_ingress,
    is_untrusted_ingress_active,
    reset_untrusted_ingress,
    set_untrusted_ingress,
)

__all__ = [
    "DISALLOWED_UNTRUSTED_PERMISSIONS",
    "DISALLOWED_UNTRUSTED_TOOLS",
    "NegativeConstraint",
    "NegativeConstraintComplianceGate",
    "NegativeConstraintVerdict",
    "TaintLabel",
    "TaintTracker",
    "VetoAction",
    "filter_untrusted_ingress_tools",
    "get_compliance_gate",
    "get_taint_tracker",
    "is_tool_allowed_under_untrusted_ingress",
    "is_untrusted_ingress_active",
    "reset_compliance_gate",
    "reset_taint_tracker",
    "reset_untrusted_ingress",
    "set_untrusted_ingress",
]

