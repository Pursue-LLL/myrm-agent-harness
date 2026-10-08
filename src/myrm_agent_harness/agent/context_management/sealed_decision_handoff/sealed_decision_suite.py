# [INPUT] DecisionInvalidationGraph, PreSealSecretMasker, DecisionSealPacker, DecisionStorageDriver
# [OUTPUT] EndToEndSealedDecisionHandoffSuite, SealedHandoffConfig
# [POS] Unified facade suite for cryptographic sealed decision handoff, secret masking, and handoff sanity

"""Unified facade suite for end-to-end sealed decision handoff and cryptographic continuity."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from myrm_agent_harness.agent.context_management.sealed_decision_handoff.decision_invalidation_graph import (
    DecisionInvalidationGraph,
)
from myrm_agent_harness.agent.context_management.sealed_decision_handoff.decision_seal_packer import (
    DecisionSealPacker,
)
from myrm_agent_harness.agent.context_management.sealed_decision_handoff.sealed_decision_types import (
    DecisionNode,
    HandoffDecisionPackage,
    HandoffSanityReport,
    NegativeInvariant,
    SealedDecisionError,
    SealedReceipt,
)
from myrm_agent_harness.agent.context_management.sealed_decision_handoff.secret_masker import (
    PreSealSecretMasker,
)
from myrm_agent_harness.agent.context_management.sealed_decision_handoff.storage_driver import (
    DecisionStorageDriver,
    SandboxVolumeDecisionStorageDriver,
)


@dataclass(frozen=True)
class SealedHandoffConfig:
    """Configuration parameters for sealed decision continuity."""

    storage_volume_dir: str
    default_key_ref: str = "vault://sandbox/agent_context_key"
    allowed_env_prefixes: list[str] = field(
        default_factory=lambda: [
            "APP_",
            "MYRM_",
            "WORKSPACE_",
            "PYTHON",
            "LANG",
            "PATH",
            "ENV_",
        ]
    )


class EndToEndSealedDecisionHandoffSuite:
    """End-to-end cryptographic decision handoff suite.

    Picks up the decisions themselves instead of lossy summaries, masks sensitive secrets
    prior to sealing, enforces decision invalidation graphs, and stores sealed context
    under sovereign storage with immutable version pointer chains.
    """

    def __init__(
        self,
        config: SealedHandoffConfig,
        storage_driver: DecisionStorageDriver | None = None,
        secret_masker: PreSealSecretMasker | None = None,
        seal_packer: DecisionSealPacker | None = None,
    ) -> None:
        self._config = config
        self._secret_masker = secret_masker or PreSealSecretMasker()
        self._seal_packer = seal_packer or DecisionSealPacker()
        self._storage_driver = storage_driver or SandboxVolumeDecisionStorageDriver(
            config.storage_volume_dir
        )

    @property
    def storage_driver(self) -> DecisionStorageDriver:
        """Access the underlying persistence driver."""
        return self._storage_driver

    def create_graph(self) -> DecisionInvalidationGraph:
        """Create a new decision invalidation graph."""
        return DecisionInvalidationGraph()

    def seal_and_store_decision_handoff(
        self,
        topic: str,
        graph: DecisionInvalidationGraph,
        encryption_key: bytes,
        summary: str,
        raw_env_vars: dict[str, str] | None = None,
        trace_artifacts: dict[str, str] | None = None,
        key_ref: str | None = None,
    ) -> tuple[SealedReceipt, HandoffSanityReport]:
        """Audit graph sanity, mask credentials, seal into ciphertext, and store to volume."""
        # 1. Verify sanity and cycle-freedom
        sanity_report = graph.verify_handoff_sanity()
        if not sanity_report.is_valid:
            raise SealedDecisionError(
                f"Cannot seal invalid decision graph: {', '.join(sanity_report.conflict_warnings)}"
            )

        # 2. Extract active decisions and apply content masking
        active_nodes = graph.get_active_decisions()
        sanitized_decisions: list[DecisionNode] = []
        for node in active_nodes:
            sanitized_node = DecisionNode(
                node_id=node.node_id,
                title=self._secret_masker.mask_text(node.title),
                intent=self._secret_masker.mask_text(node.intent),
                rationale=self._secret_masker.mask_text(node.rationale),
                chosen_option=self._secret_masker.mask_text(node.chosen_option),
                rejected_options=[
                    self._secret_masker.mask_text(opt)
                    for opt in node.rejected_options
                ],
                status="ACTIVE",
                supersedes_id=node.supersedes_id,
                timestamp_iso=node.timestamp_iso,
                metadata=self._secret_masker.mask_dict(node.metadata),
            )
            sanitized_decisions.append(sanitized_node)

        # 3. Extract and sanitize negative invariants
        raw_invariants = graph.extract_negative_invariants()
        sanitized_invariants: list[NegativeInvariant] = [
            NegativeInvariant(
                rule=self._secret_masker.mask_text(inv.rule),
                context=self._secret_masker.mask_text(inv.context),
                source_decision_id=inv.source_decision_id,
                revocation_reason=self._secret_masker.mask_text(inv.revocation_reason),
            )
            for inv in raw_invariants
        ]

        # 4. Scoped prune environment variables and trace artifacts
        sanitized_env = self._secret_masker.scoped_prune_env_vars(
            raw_env_vars or {},
            allowed_prefixes=self._config.allowed_env_prefixes,
        )
        sanitized_traces = {
            k: self._secret_masker.mask_text(v)
            for k, v in (trace_artifacts or {}).items()
        }

        # 5. Assemble package and seal
        package = HandoffDecisionPackage(
            topic=topic,
            active_decisions=sanitized_decisions,
            negative_invariants=sanitized_invariants,
            sanitized_env_vars=sanitized_env,
            trace_artifacts=sanitized_traces,
            metadata={"source_harness": "myrm-agent-harness"},
        )

        effective_key_ref = key_ref or self._config.default_key_ref
        receipt, ciphertext = self._seal_packer.seal_package(
            package=package,
            key=encryption_key,
            key_ref=effective_key_ref,
            summary=summary,
        )

        # 6. Persist to storage volume
        self._storage_driver.store_sealed_package(receipt, ciphertext)

        return receipt, sanity_report

    def open_and_hydrate_decision_handoff(
        self,
        receipt_id: str,
        decryption_key: bytes,
    ) -> HandoffDecisionPackage:
        """Fetch ciphertext by receipt ID and unseal strictly in memory pipe."""
        receipt, ciphertext = self._storage_driver.fetch_sealed_package(receipt_id)
        return self._seal_packer.unseal_package(ciphertext, receipt, decryption_key)

    @staticmethod
    def generate_negative_invariants_directive(
        package: HandoffDecisionPackage,
    ) -> str:
        """Format negative invariants into a compact LLM prompt directive (<50 tokens typical)."""
        if not package.negative_invariants:
            return ""

        lines = [
            "### STRICT NEGATIVE INVARIANTS (AVOID PREVIOUSLY REVOKED/DEAD PATHS):"
        ]
        for inv in package.negative_invariants:
            lines.append(f"- [AVOID] {inv.rule} (Reason: {inv.revocation_reason})")

        return "\n".join(lines)

    def run_first_run_provable_loop(
        self,
        encryption_key: bytes,
        topic: str = "first_run_provable_test",
    ) -> bool:
        """Run an end-to-end provable loop: seal -> store -> recall-by-receipt -> unseal -> verify."""
        graph = self.create_graph()
        graph.add_decision(
            DecisionNode(
                node_id="dec_001_initial_bootstrap",
                title="Bootstrap Verification",
                intent="Verify end-to-end cryptographic continuity loop",
                rationale="Confirm zero-leakage AEAD seal and unseal handshake",
                chosen_option="AES-256-GCM authenticated pipeline",
                rejected_options=["Plaintext transmission", "Unauthenticated CBC"],
            )
        )

        receipt, sanity = self.seal_and_store_decision_handoff(
            topic=topic,
            graph=graph,
            encryption_key=encryption_key,
            summary="First-run provable verification receipt",
        )

        if not sanity.is_valid:
            return False

        hydrated = self.open_and_hydrate_decision_handoff(
            receipt_id=receipt.receipt_id,
            decryption_key=encryption_key,
        )

        return (
            hydrated.topic == topic
            and len(hydrated.active_decisions) == 1
            and hydrated.active_decisions[0].node_id == "dec_001_initial_bootstrap"
        )
