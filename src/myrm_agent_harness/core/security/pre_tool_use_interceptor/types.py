"""Core data structures and types for PreToolUse Hook Interceptor & Key Precedence.

[INPUT]
- Tool names, argument payloads, environment variable mappings, and hard deny rules.

[OUTPUT]
- Deterministic pre-dispatch verdicts, security rejections, and API key conflict warnings.

[POS]
- Harness core security contracts for soft prompt vs hard invariant decoupling.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class HardRuleCategory(StrEnum):
    """Categorized security invariants enforced deterministically before tool use."""

    PROTECTED_BRANCH_PUSH = "PROTECTED_BRANCH_PUSH"
    DESTRUCTIVE_COMMAND = "DESTRUCTIVE_COMMAND"
    PRODUCTION_ENV_MUTATION = "PRODUCTION_ENV_MUTATION"
    DATABASE_DROP = "DATABASE_DROP"
    CUSTOM_DENY_PATTERN = "CUSTOM_DENY_PATTERN"


class HardGateActionVerdict(StrEnum):
    """Action verdict produced by pre-tool dispatch inspection."""

    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    CONFIRM_REQUIRED = "CONFIRM_REQUIRED"


class HardGateSecurityRejectionError(PermissionError):
    """Exception raised when a tool invocation violates a deterministic hard invariant."""

    def __init__(self, rule_id: str, category: HardRuleCategory, reason: str) -> None:
        super().__init__(f"[{category.value} - {rule_id}] {reason}")
        self.rule_id = rule_id
        self.category = category
        self.reason = reason



@dataclass(frozen=True)
class HardRuleSpec:
    """Specification of an immutable pre-tool use security rule."""

    rule_id: str
    category: HardRuleCategory
    pattern: str  # Regular expression pattern matched against tool payloads
    description: str
    enabled: bool = True


@dataclass(frozen=True)
class PreToolUseInterceptResult:
    """Evaluation verdict produced by PreToolUseHookInterceptor."""

    verdict: HardGateActionVerdict
    blocked_rule_id: str | None = None
    rule_category: HardRuleCategory | None = None
    rejection_reason: str | None = None
    detected_pattern: str | None = None


@dataclass(frozen=True)
class ApiKeyPrecedenceCheckResult:
    """Audit outcome analyzing environment variables vs active provider billing route."""

    has_conflict: bool
    detected_env_vars: list[str]
    active_provider: str
    warning_message: str | None = None
    recommended_action: str | None = None
