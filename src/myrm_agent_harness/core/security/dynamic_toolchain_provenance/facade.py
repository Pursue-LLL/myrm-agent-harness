"""
[POS] src/myrm_agent_harness/core/security/dynamic_toolchain_provenance/facade.py
[INPUT] time, logging, typing, .types, .provenance_verifier, .pre_install_ast_scanner, .jit_sandbox_confiner
[OUTPUT] DynamicToolchainProvenanceSuite

Unified facade for Dynamic Toolchain Supply Chain Provenance & Pre-Install Sandbox Hardening.
Orchestrates cryptographic provenance verification, static AST safety scanning,
and JIT least-privilege sandbox confinement profile issuance.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import time

from .jit_sandbox_confiner import JITSandboxConfiner
from .pre_install_ast_scanner import PreInstallASTScanner
from .provenance_verifier import ProvenanceVerificationGate
from .types import (
    ASTScanFinding,
    DynamicToolchainMetrics,
    ProvenanceStatus,
    SandboxConfinementPolicy,
    SkillProvenanceManifest,
    ToolchainVerificationDecision,
)

logger = logging.getLogger(__name__)


class DynamicToolchainProvenanceSuite:
    """Unified security suite safeguarding dynamic toolchains against supply-chain poisoning."""

    def __init__(
        self,
        verifier: ProvenanceVerificationGate | None = None,
        ast_scanner: PreInstallASTScanner | None = None,
        confiner: JITSandboxConfiner | None = None,
    ) -> None:
        self._verifier = verifier or ProvenanceVerificationGate()
        self._ast_scanner = ast_scanner or PreInstallASTScanner()
        self._confiner = confiner or JITSandboxConfiner()
        self._metrics = DynamicToolchainMetrics()

    @property
    def metrics(self) -> DynamicToolchainMetrics:
        """Retrieve cumulative metrics for the toolchain provenance suite."""
        return self._metrics

    def evaluate_and_install_skill(
        self,
        source_code: str,
        manifest: SkillProvenanceManifest,
    ) -> ToolchainVerificationDecision:
        """Execute end-to-end provenance verification, AST static scan, and sandbox confinement."""
        now = time.time()
        self._metrics.provenance_checks_total += 1

        # 1. Verify cryptographic supply chain provenance
        prov_status, prov_explanation = self._verifier.verify_provenance(source_code, manifest)
        if prov_status != ProvenanceStatus.VERIFIED:
            self._metrics.provenance_rejected_total += 1
            self._metrics.installations_blocked_total += 1
            return ToolchainVerificationDecision(
                skill_id=manifest.skill_id,
                provenance_status=prov_status,
                is_provenance_valid=False,
                ast_findings=[],
                is_ast_clean=False,
                is_installation_approved=False,
                confinement_policy=None,
                explanation=prov_explanation,
                timestamp=now,
            )

        self._metrics.provenance_verified_total += 1

        # 2. Run pre-install static AST hardening scan
        self._metrics.ast_scans_total += 1
        findings: list[ASTScanFinding] = self._ast_scanner.scan_source_code(
            source_code,
            skill_id=manifest.skill_id,
        )

        if findings:
            self._metrics.ast_violations_detected_total += len(findings)
            self._metrics.installations_blocked_total += 1
            explanation = (
                f"Installation rejected: AST scan detected {len(findings)} security violations "
                f"in skill '{manifest.skill_id}'."
            )
            return ToolchainVerificationDecision(
                skill_id=manifest.skill_id,
                provenance_status=prov_status,
                is_provenance_valid=True,
                ast_findings=findings,
                is_ast_clean=False,
                is_installation_approved=False,
                confinement_policy=None,
                explanation=explanation,
                timestamp=now,
            )

        # 3. Issue JIT least-privilege sandbox confinement policy
        policy = self._confiner.issue_confinement_policy(manifest)
        self._metrics.confinements_issued_total += 1
        self._metrics.installations_approved_total += 1

        approved_explanation = (
            f"Skill '{manifest.skill_id}@{manifest.version}' successfully verified and granted "
            f"confinement policy {policy.policy_id}."
        )
        return ToolchainVerificationDecision(
            skill_id=manifest.skill_id,
            provenance_status=prov_status,
            is_provenance_valid=True,
            ast_findings=[],
            is_ast_clean=True,
            is_installation_approved=True,
            confinement_policy=policy,
            explanation=approved_explanation,
            timestamp=now,
        )

    def verify_provenance_only(
        self,
        source_code: str,
        manifest: SkillProvenanceManifest,
    ) -> tuple[ProvenanceStatus, str]:
        """Perform provenance verification step only."""
        return self._verifier.verify_provenance(source_code, manifest)

    def scan_ast_only(self, source_code: str, skill_id: str = "") -> list[ASTScanFinding]:
        """Perform AST static scan only."""
        return self._ast_scanner.scan_source_code(source_code, skill_id=skill_id)

    def is_network_call_permitted(self, policy: SandboxConfinementPolicy, domain: str) -> bool:
        """Check if domain is within confinement policy allowed list."""
        return self._confiner.is_network_call_permitted(policy, domain)

    def is_path_access_permitted(self, policy: SandboxConfinementPolicy, path: str) -> bool:
        """Check if filesystem path is permitted under confinement policy."""
        return self._confiner.is_path_access_permitted(policy, path)

    def is_env_access_permitted(self, policy: SandboxConfinementPolicy, env_key: str) -> bool:
        """Check if environment variable key is permitted under confinement policy."""
        return self._confiner.is_env_access_permitted(policy, env_key)

    def register_trusted_publisher(self, publisher_id: str) -> None:
        """Register a new trusted publisher identity."""
        self._verifier.register_trusted_publisher(publisher_id)

    def revoke_trusted_publisher(self, publisher_id: str) -> None:
        """Revoke a publisher from trusted set."""
        self._verifier.revoke_trusted_publisher(publisher_id)

    def generate_valid_signature(self, publisher_id: str, source_sha256: str) -> str:
        """Helper to generate deterministic HMAC signature for testing or packaging."""
        return self._verifier.generate_valid_signature(publisher_id, source_sha256)
