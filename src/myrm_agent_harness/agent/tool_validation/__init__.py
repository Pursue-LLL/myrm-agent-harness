"""Mixed batch tool validation, auto-repair, and role alternation guard suite.

[OUTPUT]
- ToolValidationAction: Action outcomes for batch validation decisions.
- ToolCallEnvelope: Structured container for inbound model tool calls.
- ToolCallResult: Canonical role='tool' message object satisfying LLM API invariants.
- ToolValidationVerdict: Complete validation verdict containing executable calls and synthetic results.
- RoleAlternationViolationError: Exception thrown when conversation history violates strict role alternation.
- ToolNameFuzzyRepairer: Fuzzy matcher and alias repairer for tool names.
- ToolCallIdUniquifier: Idempotent session-level tool call ID deduplicator.
- RoleAlternationGuard: Invariant verifier and interrupted sequence closer.
- MixedBatchToolValidator: Core production validator with 3-strike partial exit and split execution.

[INPUT]
- __future__

[OUTPUT]
- (模块级副作用与注册)

[POS]
Mixed batch tool validation, auto-repair, and role alternation guard suite.
"""

from __future__ import annotations

from myrm_agent_harness.agent.tool_validation.batch_validator import (
    MixedBatchToolValidator,
)
from myrm_agent_harness.agent.tool_validation.fuzzy_repair import (
    ToolCallIdUniquifier,
    ToolNameFuzzyRepairer,
)
from myrm_agent_harness.agent.tool_validation.role_alternation_guard import (
    RoleAlternationGuard,
)
from myrm_agent_harness.agent.tool_validation.validation_types import (
    RoleAlternationViolationError,
    ToolCallEnvelope,
    ToolCallResult,
    ToolValidationAction,
    ToolValidationVerdict,
)

__all__ = [
    "MixedBatchToolValidator",
    "RoleAlternationGuard",
    "RoleAlternationViolationError",
    "ToolCallEnvelope",
    "ToolCallIdUniquifier",
    "ToolCallResult",
    "ToolNameFuzzyRepairer",
    "ToolValidationAction",
    "ToolValidationVerdict",
]
