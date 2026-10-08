"""Fail-closed LLM Egress Guard enforcing explicit domain allowlists and credential binding.

[INPUT]
- Outbound request destination URLs/domains, presented credential identifiers, and LlmEgressPolicy.

[OUTPUT]
- LlmEgressEvaluationVerdict determining whether outbound egress is permitted to proceed.

[POS]
- Harness core security guard ensuring zero un-audited or hijacked LLM/API outbound connections.
"""

from __future__ import annotations

import uuid

from myrm_agent_harness.core.security.llm_egress_guard.policy_validator import (
    extract_canonical_host,
    matches_domain_pattern,
)
from myrm_agent_harness.core.security.llm_egress_guard.types import (
    LlmEgressCredentialBindingError,
    LlmEgressDefaultDenyError,
    LlmEgressEvaluationVerdict,
    LlmEgressPolicy,
    LlmEgressVerdict,
)


class LlmEgressGuard:
    """Evaluates outbound network egress against explicit default-deny policies."""

    def __init__(self, policy: LlmEgressPolicy | None = None) -> None:
        self._policy = policy

    def set_policy(self, policy: LlmEgressPolicy) -> None:
        """Update or install an active egress policy."""
        self._policy = policy

    def get_policy(self) -> LlmEgressPolicy | None:
        """Retrieve the currently active egress policy."""
        return self._policy

    def clear_policy(self) -> None:
        """Clear active policy, immediately returning guard to fail-closed state."""
        self._policy = None

    def evaluate_egress(
        self,
        target_url_or_domain: str,
        presented_credential_id: str | None = None,
    ) -> LlmEgressEvaluationVerdict:
        """Evaluate an outbound egress candidate through default-deny and credential binding."""
        audit_id = f"egr-{uuid.uuid4().hex[:12]}"

        # 1. Fail-closed if no policy is configured
        if self._policy is None:
            return LlmEgressEvaluationVerdict(
                verdict=LlmEgressVerdict.BLOCKED_NO_POLICY,
                is_permitted=False,
                domain="",
                matched_rule_id=None,
                bound_credential_id=None,
                audit_id=audit_id,
                rationale="Egress blocked by fail-closed default-deny policy: no explicit egress policy is active.",
            )

        host = extract_canonical_host(target_url_or_domain)
        if not host:
            return LlmEgressEvaluationVerdict(
                verdict=LlmEgressVerdict.BLOCKED_INVALID_TARGET,
                is_permitted=False,
                domain=target_url_or_domain,
                matched_rule_id=None,
                bound_credential_id=None,
                audit_id=audit_id,
                rationale=f"Invalid target URL or hostname: '{target_url_or_domain}'.",
            )

        # 2. Check rules in explicit allowlist
        for rule in self._policy.allowed_rules:
            if matches_domain_pattern(host, rule.domain_pattern):
                # Verify credential binding if required
                if rule.require_credential_binding and (
                    presented_credential_id is None
                    or presented_credential_id not in rule.bound_credential_ids
                ):
                    return LlmEgressEvaluationVerdict(
                        verdict=LlmEgressVerdict.BLOCKED_CREDENTIAL_MISMATCH,
                        is_permitted=False,
                        domain=host,
                        matched_rule_id=rule.rule_id,
                        bound_credential_id=presented_credential_id,
                            audit_id=audit_id,
                            rationale=f"Credential binding violation: credential '{presented_credential_id}' "
                            f"is not authorized for destination domain '{host}' under rule {rule.rule_id}.",
                        )

                return LlmEgressEvaluationVerdict(
                    verdict=LlmEgressVerdict.PERMITTED,
                    is_permitted=True,
                    domain=host,
                    matched_rule_id=rule.rule_id,
                    bound_credential_id=presented_credential_id,
                    audit_id=audit_id,
                    rationale=f"Egress authorized by rule {rule.rule_id} for domain pattern '{rule.domain_pattern}'.",
                )

        # 3. Default-deny: domain not in explicit allowlist
        return LlmEgressEvaluationVerdict(
            verdict=LlmEgressVerdict.BLOCKED_DOMAIN_NOT_ALLOWED,
            is_permitted=False,
            domain=host,
            matched_rule_id=None,
            bound_credential_id=presented_credential_id,
            audit_id=audit_id,
            rationale=f"Egress blocked by default-deny policy: destination domain '{host}' is not on the allowlist.",
        )

    def assert_egress_permitted(
        self,
        target_url_or_domain: str,
        presented_credential_id: str | None = None,
    ) -> LlmEgressEvaluationVerdict:
        """Evaluate egress candidate and raise domain exception if blocked."""
        verdict = self.evaluate_egress(
            target_url_or_domain=target_url_or_domain,
            presented_credential_id=presented_credential_id,
        )

        if verdict.verdict == LlmEgressVerdict.BLOCKED_CREDENTIAL_MISMATCH:
            raise LlmEgressCredentialBindingError(verdict.rationale)

        if not verdict.is_permitted:
            raise LlmEgressDefaultDenyError(verdict.rationale)

        return verdict
