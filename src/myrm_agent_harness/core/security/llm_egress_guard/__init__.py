"""LLM Egress Default-Deny & Credential Binding Suite.

[INPUT]
- Domain allowlist policies, target URLs, and credential identifiers.

[OUTPUT]
- Public exports of domain types, policy validator, and fail-closed egress guard.

[POS]
- Harness core security suite enforcing strict default-deny network egress.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.llm_egress_guard.guard import (
    LlmEgressGuard,
)
from myrm_agent_harness.core.security.llm_egress_guard.policy_validator import (
    extract_canonical_host,
    matches_domain_pattern,
)
from myrm_agent_harness.core.security.llm_egress_guard.types import (
    DomainAllowlistRule,
    LlmEgressCredentialBindingError,
    LlmEgressDefaultDenyError,
    LlmEgressEvaluationVerdict,
    LlmEgressPolicy,
    LlmEgressVerdict,
)

__all__ = [
    "DomainAllowlistRule",
    "LlmEgressCredentialBindingError",
    "LlmEgressDefaultDenyError",
    "LlmEgressEvaluationVerdict",
    "LlmEgressGuard",
    "LlmEgressPolicy",
    "LlmEgressVerdict",
    "extract_canonical_host",
    "matches_domain_pattern",
]
