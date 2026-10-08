"""MemoryManager mixin for cross-agent composable context and memory conflict arbitration.

[INPUT]
- toolkits.memory.cross_agent.arbitrator::MultiAgentConflictArbitrator (POS: arbitrator)
- toolkits.memory.cross_agent.integrity::HandoffIntegrityPipeline (POS: integrity)
- toolkits.memory.cross_agent.projector::ComposableContextProjector (POS: projector)
- toolkits.memory.cross_agent.types::* (POS: contracts)

[OUTPUT]
- MemoryManagerCrossAgentMixin: runtime orchestration methods for multi-agent context projection and conflict arbitration

[POS]
Partial mixin for MemoryManager providing 4-layer virtual reference context projection, deterministic 3-tier divergence arbitration, and sealed task handoffs.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.cross_agent.arbitrator import (
        MultiAgentConflictArbitrator,
    )
    from myrm_agent_harness.toolkits.memory.cross_agent.integrity import (
        HandoffIntegrityPipeline,
    )
    from myrm_agent_harness.toolkits.memory.cross_agent.projector import (
        ComposableContextProjector,
    )
    from myrm_agent_harness.toolkits.memory.cross_agent.types import (
        AgentMemoryDivergence,
        ArbitrationOutcome,
        ComposableContextProjection,
        HandoffPacket,
        HandoffVerificationResult,
        MemoryAssertion,
    )


class MemoryManagerCrossAgentMixin:
    """Provides methods for composable context projection, divergence arbitration, and task handoffs."""

    def project_composable_context(
        self,
        agent_id: str,
        session_id: str,
        *,
        global_ground_truth: list[str] | None = None,
        profile_tools_memory: list[str] | None = None,
        private_scratchpad: str | None = None,
        handoff_packet: HandoffPacket | None = None,
        token_budget: int | None = None,
        projector: ComposableContextProjector | None = None,
    ) -> ComposableContextProjection:
        """Compose 4-layer context isolating private scratchpad while stabilizing prefix for KV cache reuse."""
        from myrm_agent_harness.toolkits.memory.cross_agent.projector import (
            ComposableContextProjector,
        )

        active_projector = projector or ComposableContextProjector()
        return active_projector.project_for_agent(
            agent_id=agent_id,
            session_id=session_id,
            global_ground_truth=global_ground_truth,
            profile_tools_memory=profile_tools_memory,
            private_scratchpad=private_scratchpad,
            handoff_packet=handoff_packet,
            token_budget=token_budget,
        )

    def arbitrate_memory_divergence(
        self,
        divergence: AgentMemoryDivergence,
        *,
        workspace_root: Path | str | None = None,
        arbitrator: MultiAgentConflictArbitrator | None = None,
    ) -> ArbitrationOutcome:
        """Settle a memory conflict between two agents using 3-tier deterministic arbitration."""
        from myrm_agent_harness.toolkits.memory.cross_agent.arbitrator import (
            MultiAgentConflictArbitrator,
        )

        active_arbitrator = arbitrator or MultiAgentConflictArbitrator(workspace_root=workspace_root)
        return active_arbitrator.arbitrate_divergence(divergence)

    def detect_and_arbitrate_memory_conflicts(
        self,
        assertions_agent_a: list[MemoryAssertion],
        assertions_agent_b: list[MemoryAssertion],
        *,
        workspace_root: Path | str | None = None,
        arbitrator: MultiAgentConflictArbitrator | None = None,
    ) -> list[ArbitrationOutcome]:
        """Detect all conflicting assertions between two agents and arbitrate each divergence."""
        from myrm_agent_harness.toolkits.memory.cross_agent.arbitrator import (
            MultiAgentConflictArbitrator,
        )

        active_arbitrator = arbitrator or MultiAgentConflictArbitrator(workspace_root=workspace_root)
        divergences = active_arbitrator.detect_divergences(assertions_agent_a, assertions_agent_b)
        return [active_arbitrator.arbitrate_divergence(d) for d in divergences]

    def seal_agent_handoff(
        self,
        source_agent_id: str,
        target_agent_id: str,
        task_id: str,
        context_snapshot: str,
        assertions: list[MemoryAssertion] | None = None,
        secret_salt: str = "",
        pipeline: HandoffIntegrityPipeline | None = None,
    ) -> HandoffPacket:
        """Create a cryptographically signed handoff packet for successor agent."""
        from myrm_agent_harness.toolkits.memory.cross_agent.integrity import (
            HandoffIntegrityPipeline,
        )

        active_pipeline = pipeline or HandoffIntegrityPipeline(secret_salt=secret_salt)
        return active_pipeline.seal_handoff(
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            task_id=task_id,
            context_snapshot=context_snapshot,
            assertions=assertions,
            secret_salt=secret_salt,
        )

    def verify_agent_handoff(
        self,
        packet: HandoffPacket,
        secret_salt: str = "",
        pipeline: HandoffIntegrityPipeline | None = None,
    ) -> HandoffVerificationResult:
        """Verify the integrity seal and assertions of an incoming handoff packet."""
        from myrm_agent_harness.toolkits.memory.cross_agent.integrity import (
            HandoffIntegrityPipeline,
        )

        active_pipeline = pipeline or HandoffIntegrityPipeline(secret_salt=secret_salt)
        return active_pipeline.verify_handoff(packet, secret_salt=secret_salt)
