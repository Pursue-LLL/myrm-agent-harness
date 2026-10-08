"""Three-dimensional continuous runtime network enforcer.

[INPUT]
- .types::EnforcementDecision, NetworkPolicyRule, ProtocolKind, RuntimeHopCheckRequest, RuntimeHopCheckResult
- stdlib fnmatch, logging

[OUTPUT]
- ThreeDimContinuousEnforcer: enforces binaries x endpoints x path glob x protocol policies

[POS]
Continuous runtime security layer aligned with NVIDIA OpenShell's 3D policy model.
Validates process binaries against endpoints, matches most specific path glob,
and strictly blocks unauthorized protocol upgrade headers.
Strictly avoids Any types; enforced under 400 lines limit.
"""

from __future__ import annotations

import fnmatch
import logging

from myrm_agent_harness.core.security.kernel_continuous_enforcement.types import (
    EnforcementDecision,
    NetworkPolicyRule,
    ProtocolKind,
    RuntimeHopCheckRequest,
    RuntimeHopCheckResult,
)

logger = logging.getLogger(__name__)

# Protocols where HTTP Upgrade header represents a dangerous smuggling / tunneling vector
_UPGRADE_RESTRICTED_PROTOCOLS: frozenset[ProtocolKind] = frozenset({
    ProtocolKind.MCP,
    ProtocolKind.GRAPHQL,
    ProtocolKind.JSON_RPC,
})


class ThreeDimContinuousEnforcer:
    """3D continuous runtime policy enforcer.

    Rules evaluate in three dimensions:
    1. binaries: executing process binary must match allowed binaries list
    2. endpoints + path glob: host, port, and most specific path glob match
    3. protocol: protocol alignment and strict upgrade header blocking
    """

    def __init__(self, rules: tuple[NetworkPolicyRule, ...] = ()) -> None:
        self._rules: dict[str, NetworkPolicyRule] = {r.rule_id: r for r in rules}

    def add_rule(self, rule: NetworkPolicyRule) -> None:
        """Register or update a network policy rule."""
        self._rules[rule.rule_id] = rule

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a network policy rule by rule_id."""
        if rule_id in self._rules:
            del self._rules[rule_id]
            return True
        return False

    def get_rules(self) -> list[NetworkPolicyRule]:
        """Return all active policy rules."""
        return list(self._rules.values())

    def clear_rules(self) -> None:
        """Clear all active rules."""
        self._rules.clear()

    def evaluate(self, request: RuntimeHopCheckRequest) -> RuntimeHopCheckResult:
        """Evaluate a runtime network egress request against 3D policies.

        Default policy is DENY. A request is allowed if and only if:
        1. An active rule matches the target host and port.
        2. The requesting binary is listed in the rule's allowed_binaries.
        3. The request path matches the rule's path glob (most specific match chosen).
        4. The protocol matches, and if upgrade header is present, it is explicitly permitted.
        """
        # Find candidate rules matching host and port
        candidate_rules: list[NetworkPolicyRule] = []
        for rule in self._rules.values():
            if self._host_matches(rule.endpoint_host, request.host) and rule.endpoint_port == request.port:
                candidate_rules.append(rule)

        if not candidate_rules:
            return RuntimeHopCheckResult(
                decision=EnforcementDecision.DENY,
                rule_id=None,
                reason=f"No matching policy rule for endpoint {request.host}:{request.port}",
            )

        # Filter candidates by binary allowlist
        binary_matched_rules: list[NetworkPolicyRule] = []
        for rule in candidate_rules:
            if "*" in rule.allowed_binaries or request.binary_name in rule.allowed_binaries:
                binary_matched_rules.append(rule)

        if not binary_matched_rules:
            return RuntimeHopCheckResult(
                decision=EnforcementDecision.DENY,
                rule_id=None,
                reason=(
                    f"Binary '{request.binary_name}' is not permitted to access "
                    f"endpoint {request.host}:{request.port}"
                ),
            )

        # Filter by path glob and pick the most specific matching rule (longest path_glob)
        path_matched_rules: list[NetworkPolicyRule] = []
        for rule in binary_matched_rules:
            if fnmatch.fnmatch(request.path, rule.path_glob):
                path_matched_rules.append(rule)

        if not path_matched_rules:
            return RuntimeHopCheckResult(
                decision=EnforcementDecision.DENY,
                rule_id=None,
                reason=(
                    f"Request path '{request.path}' does not match any path glob for "
                    f"endpoint {request.host}:{request.port}"
                ),
            )

        # Sort candidate rules by descending specificity of path glob
        path_matched_rules.sort(key=lambda r: len(r.path_glob), reverse=True)
        best_rule = path_matched_rules[0]

        # Protocol verification
        if best_rule.protocol != request.protocol:
            return RuntimeHopCheckResult(
                decision=EnforcementDecision.DENY,
                rule_id=best_rule.rule_id,
                reason=(
                    f"Protocol mismatch: rule requires '{best_rule.protocol.value}' "
                    f"but request attempted '{request.protocol.value}'"
                ),
            )

        # Protocol upgrade header inspection (mcp / graphql / json-rpc)
        if (
            request.has_upgrade_header
            and best_rule.protocol in _UPGRADE_RESTRICTED_PROTOCOLS
            and not best_rule.allow_upgrade_header
        ):
                logger.warning(
                    "SECURITY INTERCEPTION: Protocol upgrade header rejected for %s endpoint %s:%d (Rule: %s)",
                    best_rule.protocol.value,
                    request.host,
                    request.port,
                    best_rule.rule_id,
                )
                return RuntimeHopCheckResult(
                    decision=EnforcementDecision.DENY,
                    rule_id=best_rule.rule_id,
                    reason=(
                        f"Protocol upgrade header forbidden for {best_rule.protocol.value} "
                        f"endpoint {request.host}:{request.port}"
                    ),
                    violates_protocol_upgrade=True,
                )

        return RuntimeHopCheckResult(
            decision=EnforcementDecision.ALLOW,
            rule_id=best_rule.rule_id,
            reason=f"Request allowed by rule '{best_rule.rule_id}'",
        )

    def _host_matches(self, rule_host: str, request_host: str) -> bool:
        if rule_host == "*" or rule_host.lower() == request_host.lower():
            return True
        if rule_host.startswith("*."):
            suffix = rule_host[2:].lower()
            return request_host.lower().endswith("." + suffix) or request_host.lower() == suffix
        return False
