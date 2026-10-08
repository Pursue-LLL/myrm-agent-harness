"""Type definitions for Kernel Continuous Enforcement, Formal Policy Prover,
Revocation Residue, and Supply Chain Verification Suite.

[INPUT]
- stdlib dataclasses, enum, typing

[OUTPUT]
- ProtocolKind: supported network protocol classifications
- EnforcementDecision: allow or deny action
- NetworkPolicyRule: rule binding binary, endpoint, path glob, and protocol
- RuntimeHopCheckRequest: request evaluating runtime binary access
- RuntimeHopCheckResult: evaluation outcome with rule attribution
- PolicyChangeProposal: agent-proposed policy relaxation
- ProverValidationResult: outcome of formal verification of proposed policy
- RevocationResidueReport: report assessing lingering processes, sockets, memory files, and tokens

[POS]
Core schema definitions for OpenShell-aligned continuous runtime enforcement.
Strictly avoids Any types; enforced under 400 lines limit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ProtocolKind(StrEnum):
    """Network protocol classifications for deep request inspection."""

    REST = "rest"
    WEBSOCKET = "websocket"
    GRAPHQL = "graphql"
    MCP = "mcp"
    JSON_RPC = "json-rpc"
    TCP = "tcp"


class EnforcementDecision(StrEnum):
    """Enforcement decision actions."""

    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class NetworkPolicyRule:
    """3D Network policy rule binding binaries x endpoints x path glob x protocol."""

    rule_id: str
    allowed_binaries: tuple[str, ...]
    endpoint_host: str
    endpoint_port: int
    path_glob: str = "*"
    protocol: ProtocolKind = ProtocolKind.REST
    allow_upgrade_header: bool = False
    provider_binding: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeHopCheckRequest:
    """Request evaluating whether an executing binary may access a network endpoint."""

    binary_name: str
    host: str
    port: int
    path: str = "/"
    protocol: ProtocolKind = ProtocolKind.REST
    has_upgrade_header: bool = False


@dataclass(frozen=True, slots=True)
class RuntimeHopCheckResult:
    """Outcome of 3D continuous enforcement evaluation."""

    decision: EnforcementDecision
    rule_id: str | None
    reason: str
    violates_protocol_upgrade: bool = False


@dataclass(frozen=True, slots=True)
class PolicyChangeProposal:
    """Agent-driven proposal for minimal-privilege policy relaxation."""

    proposal_id: str
    agent_id: str
    proposed_rules: tuple[NetworkPolicyRule, ...]
    justification: str
    timestamp_iso: str


@dataclass(frozen=True, slots=True)
class ProverValidationResult:
    """Formal verification analysis of a policy change proposal."""

    proposal_id: str
    is_safe: bool
    risk_score: float
    flagged_risks: tuple[str, ...]
    formal_proof_summary: str
    requires_human_approval: bool


@dataclass(frozen=True, slots=True)
class RevocationResidueReport:
    """Audit report verifying whether any execution artifacts survived after run termination."""

    run_id: str
    timestamp_iso: str
    lingering_pids: tuple[int, ...] = field(default_factory=tuple)
    lingering_sockets: tuple[str, ...] = field(default_factory=tuple)
    lingering_tmp_files: tuple[str, ...] = field(default_factory=tuple)
    lingering_cached_tokens: tuple[str, ...] = field(default_factory=tuple)
    is_fully_clean: bool = True
