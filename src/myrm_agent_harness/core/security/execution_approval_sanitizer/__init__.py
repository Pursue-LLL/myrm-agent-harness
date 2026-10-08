"""
[POS] src/myrm_agent_harness/core/security/execution_approval_sanitizer/__init__.py
[INPUT] types, pattern_rules, redaction_engine, facade
[OUTPUT] Public API exports for Execution Approval Secret Redaction & In-Band Presentation Sanitizer Suite
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from .facade import ExecutionApprovalSanitizerFacade
from .pattern_rules import (
    DEFAULT_SECRET_RULES,
    SecretPatternRule,
    calculate_shannon_entropy,
    is_whitelisted_token,
)
from .redaction_engine import ExecutionApprovalSecretRedactionEngine
from .types import (
    ApprovalPayloadRequest,
    RedactionFinding,
    SanitizationResult,
    SanitizerMetrics,
    SecretType,
)

__all__ = [
    "DEFAULT_SECRET_RULES",
    "ApprovalPayloadRequest",
    "ExecutionApprovalSanitizerFacade",
    "ExecutionApprovalSecretRedactionEngine",
    "RedactionFinding",
    "SanitizationResult",
    "SanitizerMetrics",
    "SecretPatternRule",
    "SecretType",
    "calculate_shannon_entropy",
    "is_whitelisted_token",
]
