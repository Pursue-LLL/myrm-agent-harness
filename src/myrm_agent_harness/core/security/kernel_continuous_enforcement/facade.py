"""Facade for Kernel Continuous Enforcement, Formal Policy Prover,
and Revocation Residue Suite.

[INPUT]
- .types::(EnforcementDecision, NetworkPolicyRule, PolicyChangeProposal, ProverValidationResult,
           RevocationResidueReport, RuntimeHopCheckRequest, RuntimeHopCheckResult)
- .three_dim_enforcer::ThreeDimContinuousEnforcer
- .formal_policy_prover::FormalPolicyProver
- .revocation_residue_verifier::RevocationResidueVerifier
- stdlib collections.abc, threading

[OUTPUT]
- KernelContinuousEnforcementFacade: unified orchestration of 3D runtime enforcement,
  formal prover gates, policy hot-loading, and revocation residue auditing

[POS]
Main entry point for continuous runtime enforcement suite in harness.
Strictly avoids Any types; enforced under 400 lines limit.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence

from myrm_agent_harness.core.security.kernel_continuous_enforcement.formal_policy_prover import (
    FormalPolicyProver,
)
from myrm_agent_harness.core.security.kernel_continuous_enforcement.revocation_residue_verifier import (
    RevocationResidueVerifier,
)
from myrm_agent_harness.core.security.kernel_continuous_enforcement.three_dim_enforcer import (
    ThreeDimContinuousEnforcer,
)
from myrm_agent_harness.core.security.kernel_continuous_enforcement.types import (
    NetworkPolicyRule,
    PolicyChangeProposal,
    ProverValidationResult,
    RevocationResidueReport,
    RuntimeHopCheckRequest,
    RuntimeHopCheckResult,
)


class KernelContinuousEnforcementFacade:
    """Unified facade managing 3D continuous enforcement, formal prover, and residue auditing."""

    def __init__(self, initial_rules: tuple[NetworkPolicyRule, ...] = ()) -> None:
        self._enforcer: ThreeDimContinuousEnforcer = ThreeDimContinuousEnforcer(initial_rules)
        self._prover: FormalPolicyProver = FormalPolicyProver()
        self._residue_verifier: RevocationResidueVerifier = RevocationResidueVerifier()
        self._proposals: dict[str, tuple[PolicyChangeProposal, ProverValidationResult, str]] = {}
        self._residue_reports: list[RevocationResidueReport] = []
        self._lock: threading.Lock = threading.Lock()

    @property
    def enforcer(self) -> ThreeDimContinuousEnforcer:
        return self._enforcer

    @property
    def prover(self) -> FormalPolicyProver:
        return self._prover

    @property
    def residue_verifier(self) -> RevocationResidueVerifier:
        return self._residue_verifier

    def evaluate_egress(self, request: RuntimeHopCheckRequest) -> RuntimeHopCheckResult:
        """Evaluate a runtime network egress request against 3D policies."""
        with self._lock:
            return self._enforcer.evaluate(request)

    def submit_proposal(self, proposal: PolicyChangeProposal) -> ProverValidationResult:
        """Submit a policy relaxation proposal to the formal prover."""
        proof_result = self._prover.prove_proposal(proposal)
        with self._lock:
            self._proposals[proposal.proposal_id] = (proposal, proof_result, "PENDING")
        return proof_result

    def approve_proposal(self, proposal_id: str) -> bool:
        """Approve a pending proposal and hot-load its proposed rules into the enforcer."""
        with self._lock:
            entry = self._proposals.get(proposal_id)
            if entry is None or entry[2] != "PENDING":
                return False
            proposal, proof, _ = entry
            for rule in proposal.proposed_rules:
                self._enforcer.add_rule(rule)
            self._proposals[proposal_id] = (proposal, proof, "APPROVED")
            return True

    def reject_proposal(self, proposal_id: str) -> bool:
        """Reject a pending proposal."""
        with self._lock:
            entry = self._proposals.get(proposal_id)
            if entry is None or entry[2] != "PENDING":
                return False
            proposal, proof, _ = entry
            self._proposals[proposal_id] = (proposal, proof, "REJECTED")
            return True

    def get_proposals(self) -> list[tuple[PolicyChangeProposal, ProverValidationResult, str]]:
        """Return all submitted proposals with their proof verdicts and statuses."""
        with self._lock:
            return list(self._proposals.values())

    def audit_revocation(
        self,
        run_id: str,
        active_pids: Sequence[int] = (),
        open_sockets: Sequence[str] = (),
        temp_files: Sequence[str] = (),
        cached_tokens: Sequence[str] = (),
    ) -> RevocationResidueReport:
        """Execute a revocation residue audit and record report."""
        report = self._residue_verifier.audit_run_residue(
            run_id=run_id,
            active_pids=active_pids,
            open_sockets=open_sockets,
            temp_files=temp_files,
            cached_tokens=cached_tokens,
        )
        with self._lock:
            self._residue_reports.append(report)
        return report

    def get_residue_reports(self) -> list[RevocationResidueReport]:
        """Return all recorded revocation residue reports."""
        with self._lock:
            return list(self._residue_reports)
