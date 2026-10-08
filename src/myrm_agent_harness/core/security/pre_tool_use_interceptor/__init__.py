"""PreToolUse Hook Interceptor & API Key Precedence Suite.

Decouples soft prompt instructions from hard non-negotiable gates, providing
deterministic pre-dispatch inspection for commands/files and silent surcharge prevention.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.pre_tool_use_interceptor.interceptor import (
    PreToolUseHookInterceptor,
)
from myrm_agent_harness.core.security.pre_tool_use_interceptor.precedence_detector import (
    ApiKeyPrecedenceDetector,
)
from myrm_agent_harness.core.security.pre_tool_use_interceptor.rules import (
    DEFAULT_HARD_RULES,
)
from myrm_agent_harness.core.security.pre_tool_use_interceptor.types import (
    ApiKeyPrecedenceCheckResult,
    HardGateActionVerdict,
    HardGateSecurityRejectionError,
    HardRuleCategory,
    HardRuleSpec,
    PreToolUseInterceptResult,
)

__all__ = [
    "ApiKeyPrecedenceCheckResult",
    "ApiKeyPrecedenceDetector",
    "DEFAULT_HARD_RULES",
    "HardGateActionVerdict",
    "HardGateSecurityRejectionError",
    "HardRuleCategory",
    "HardRuleSpec",
    "PreToolUseHookInterceptor",
    "PreToolUseInterceptResult",
]
