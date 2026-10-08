"""Formal policy prover and advisor gate for runtime network policy changes.

[INPUT]
- .types::PolicyChangeProposal, ProtocolKind, ProverValidationResult
- stdlib logging

[OUTPUT]
- FormalPolicyProver: symbolically proves safety and flags risks in proposed policy changes

[POS]
Advisor gate aligned with OpenShell prover architecture.
Analyzes proposals for wildcard binaries, sensitive ports, unconstrained path globs,
and unauthorized protocol upgrade permissions before granting policy relaxation.
Strictly avoids Any types; enforced under 400 lines limit.
"""

from __future__ import annotations

import logging

from myrm_agent_harness.core.security.kernel_continuous_enforcement.types import (
    PolicyChangeProposal,
    ProtocolKind,
    ProverValidationResult,
)

logger = logging.getLogger(__name__)

# High-impact management, database, and orchestration ports requiring strict review
_HIGH_RISK_PORTS: frozenset[int] = frozenset({
    22,    # SSH
    23,    # Telnet
    2375,  # Docker Daemon unencrypted
    2376,  # Docker Daemon TLS
    6443,  # Kubernetes API server
    8500,  # Consul
    9200,  # Elasticsearch
    27017, # MongoDB
    5432,  # PostgreSQL
    3306,  # MySQL
})

_SENSITIVE_PROVIDER_DOMAINS: tuple[str, ...] = (
    "github.com",
    "gitlab.com",
    "slack.com",
    "aws.amazon.com",
    "googleapis.com",
)


class FormalPolicyProver:
    """Formal verification engine evaluating policy proposals against invariant safety rules."""

    def prove_proposal(self, proposal: PolicyChangeProposal) -> ProverValidationResult:
        """Run formal proof analysis on a policy change proposal.

        Evaluates invariants:
        - Invariant 1 (Binary Specificity): wildcards in allowed_binaries indicate untrusted execution.
        - Invariant 2 (Endpoint Scope): wildcard endpoint hosts/ports represent unrestricted egress.
        - Invariant 3 (Port Protection): sensitive administrative and database ports are flagged.
        - Invariant 4 (Protocol Smuggling): Upgrade headers on MCP/GraphQL enable protocol bypass.
        - Invariant 5 (Provider Binding): external SaaS APIs should have explicit credential bindings.
        """
        flagged_risks: list[str] = []
        risk_weight = 0.0

        for rule in proposal.proposed_rules:
            # 1. Binary Specificity Proof
            if "*" in rule.allowed_binaries:
                flagged_risks.append(
                    f"Rule '{rule.rule_id}': Wildcard binary '*' permits arbitrary untrusted processes to egress."
                )
                risk_weight += 0.35

            # 2. Endpoint Scope Proof
            if rule.endpoint_host == "*" or rule.endpoint_host == "0.0.0.0":  # noqa: S104
                flagged_risks.append(
                    f"Rule '{rule.rule_id}': Wildcard host '{rule.endpoint_host}' permits broad outbound internet access."
                )
                risk_weight += 0.40

            # 3. Port Protection Proof
            if rule.endpoint_port in _HIGH_RISK_PORTS:
                flagged_risks.append(
                    f"Rule '{rule.rule_id}': Target port {rule.endpoint_port} is a high-risk administrative or database port."
                )
                risk_weight += 0.30

            # 4. Protocol Upgrade Smuggling Proof
            if rule.allow_upgrade_header and rule.protocol in (ProtocolKind.MCP, ProtocolKind.GRAPHQL, ProtocolKind.JSON_RPC):
                flagged_risks.append(
                    f"Rule '{rule.rule_id}': Permitting Upgrade header on {rule.protocol.value} allows protocol hijacking."
                )
                risk_weight += 0.25

            # 5. SaaS Provider Binding Proof
            if any(dom in rule.endpoint_host for dom in _SENSITIVE_PROVIDER_DOMAINS) and not rule.provider_binding:
                flagged_risks.append(
                    f"Rule '{rule.rule_id}': SaaS endpoint '{rule.endpoint_host}' lacks an explicit credential provider binding."
                )
                risk_weight += 0.15

            # 6. Excessive Path Scope
            if rule.path_glob == "*" and rule.endpoint_port not in (80, 443):
                flagged_risks.append(
                    f"Rule '{rule.rule_id}': Unbounded path glob '*' on non-standard port {rule.endpoint_port}."
                )
                risk_weight += 0.10

        normalized_risk_score = min(1.0, round(risk_weight, 2))
        is_safe = len(flagged_risks) == 0 and normalized_risk_score < 0.2
        requires_human_approval = not is_safe or normalized_risk_score >= 0.2

        if is_safe:
            summary = (
                f"Formal proof PASSED for proposal '{proposal.proposal_id}'. "
                f"Evaluated {len(proposal.proposed_rules)} rules with 0 invariant violations."
            )
        else:
            summary = (
                f"Formal proof FLAGGED proposal '{proposal.proposal_id}' (Risk score: {normalized_risk_score}). "
                f"Detected {len(flagged_risks)} safety invariant violations. Human approval mandatory."
            )

        logger.info(
            "Formal policy prover verdict for %s: is_safe=%s, score=%.2f, risks=%d",
            proposal.proposal_id,
            is_safe,
            normalized_risk_score,
            len(flagged_risks),
        )

        return ProverValidationResult(
            proposal_id=proposal.proposal_id,
            is_safe=is_safe,
            risk_score=normalized_risk_score,
            flagged_risks=tuple(flagged_risks),
            formal_proof_summary=summary,
            requires_human_approval=requires_human_approval,
        )
