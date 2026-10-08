"""Unit tests for cross-agent composable context, conflict arbitrator, and handoff integrity.

[INPUT]
- toolkits.memory.cross_agent.*
- pytest, tmp_path

[OUTPUT]
- TestComposableContextProjector
- TestMultiAgentConflictArbitrator
- TestHandoffIntegrityPipeline
- TestCrossAgentArbitrationTool

[POS]
Verification suite for Item 177: CrossAgentComposableContextAndConflictArbitrationEngineSuite.
"""

from __future__ import annotations

import json
from pathlib import Path

from myrm_agent_harness.toolkits.memory.cross_agent.arbitrator import (
    MultiAgentConflictArbitrator,
)
from myrm_agent_harness.toolkits.memory.cross_agent.integrity import (
    HandoffIntegrityPipeline,
)
from myrm_agent_harness.toolkits.memory.cross_agent.projector import (
    ComposableContextProjector,
)
from myrm_agent_harness.toolkits.memory.cross_agent.tool import (
    create_cross_agent_arbitration_tool,
)
from myrm_agent_harness.toolkits.memory.cross_agent.types import (
    AgentMemoryDivergence,
    ConflictResolutionPolicy,
    ContextLayerKind,
    MemoryAssertion,
)


class TestComposableContextProjector:
    """Tests for 4-layer context projection and KV cache prefix stability."""

    def test_project_layers_and_cache_prefix_stability(self) -> None:
        projector = ComposableContextProjector(default_token_budget=2048)

        # Agent A projection
        proj_a = projector.project_for_agent(
            agent_id="agent_coder",
            session_id="sess_123",
            global_ground_truth=["DB is SQLite", "Framework is FastAPI"],
            profile_tools_memory=["Tool: python_repl", "Role: Software Engineer"],
            private_scratchpad="Working on user auth",
        )

        assert len(proj_a.layers) == 4
        assert proj_a.layers[0].layer_kind == ContextLayerKind.LAYER_2_PROFILE
        assert proj_a.layers[1].layer_kind == ContextLayerKind.LAYER_3_GLOBAL
        assert proj_a.layers[2].layer_kind == ContextLayerKind.LAYER_1_PRIVATE
        assert proj_a.layers[3].layer_kind == ContextLayerKind.LAYER_4_HANDOFF
        assert proj_a.cache_prefix_hash != ""

        # Agent B projection sharing same global and profile, but different private scratchpad
        proj_b = projector.project_for_agent(
            agent_id="agent_tester",
            session_id="sess_123",
            global_ground_truth=["DB is SQLite", "Framework is FastAPI"],
            profile_tools_memory=["Tool: python_repl", "Role: Software Engineer"],
            private_scratchpad="Running pytest suite",
        )

        # KV Cache prefix hash across Layer 2 and Layer 3 MUST match for 80%+ reuse
        assert proj_a.cache_prefix_hash == proj_b.cache_prefix_hash


class TestMultiAgentConflictArbitrator:
    """Tests for 3-tier deterministic arbitration ladder."""

    def test_tier_1_ground_truth_probe(self, tmp_path: Path) -> None:
        # Create a physical file representing real repo truth
        db_config_file = tmp_path / "config.py"
        db_config_file.write_text("DATABASE_URL = 'sqlite:///test.db'", encoding="utf-8")

        arbitrator = MultiAgentConflictArbitrator(workspace_root=tmp_path)

        ast_a = MemoryAssertion(
            assertion_id="ast-a",
            subject="database_backend",
            predicate="configured_as",
            object_value="sqlite",
            confidence=0.7,
            source_agent_id="coder",
            source_reference="config.py",
        )
        ast_b = MemoryAssertion(
            assertion_id="ast-b",
            subject="database_backend",
            predicate="configured_as",
            object_value="postgres",
            confidence=0.95,
            source_agent_id="architect",
            source_reference="unrelated.py",
        )

        divergence = AgentMemoryDivergence(
            divergence_id="div-db",
            subject="database_backend",
            predicate="configured_as",
            agent_a_id="coder",
            assertion_a=ast_a,
            agent_b_id="architect",
            assertion_b=ast_b,
        )

        outcome = arbitrator.arbitrate_divergence(divergence)
        assert outcome.resolved is True
        assert outcome.policy_applied == ConflictResolutionPolicy.GROUND_TRUTH_FIRST
        assert outcome.winning_assertion.object_value == "sqlite"
        assert outcome.requires_human_confirmation is False

    def test_tier_2_coordinator_authority(self) -> None:
        arbitrator = MultiAgentConflictArbitrator(
            workspace_root=None,
            coordinator_agent_ids={"coordinator"},
        )

        ast_a = MemoryAssertion(
            assertion_id="ast-a",
            subject="deployment_strategy",
            predicate="is",
            object_value="blue_green",
            confidence=0.6,
            source_agent_id="coordinator",
        )
        ast_b = MemoryAssertion(
            assertion_id="ast-b",
            subject="deployment_strategy",
            predicate="is",
            object_value="canary",
            confidence=0.6,
            source_agent_id="worker_agent",
        )

        divergence = AgentMemoryDivergence(
            divergence_id="div-deploy",
            subject="deployment_strategy",
            predicate="is",
            agent_a_id="coordinator",
            assertion_a=ast_a,
            agent_b_id="worker_agent",
            assertion_b=ast_b,
        )

        outcome = arbitrator.arbitrate_divergence(divergence)
        assert outcome.resolved is True
        assert outcome.policy_applied == ConflictResolutionPolicy.COORDINATOR_AUTHORITY
        assert outcome.winning_assertion.source_agent_id == "coordinator"

    def test_tier_3_human_in_the_loop_suspension(self) -> None:
        arbitrator = MultiAgentConflictArbitrator(workspace_root=None)

        ast_a = MemoryAssertion(
            assertion_id="ast-a",
            subject="auth_mode",
            predicate="uses",
            object_value="jwt",
            confidence=0.8,
            source_agent_id="agent_1",
        )
        ast_b = MemoryAssertion(
            assertion_id="ast-b",
            subject="auth_mode",
            predicate="uses",
            object_value="session_cookie",
            confidence=0.8,
            source_agent_id="agent_2",
        )

        divergence = AgentMemoryDivergence(
            divergence_id="div-auth",
            subject="auth_mode",
            predicate="uses",
            agent_a_id="agent_1",
            assertion_a=ast_a,
            agent_b_id="agent_2",
            assertion_b=ast_b,
        )

        outcome = arbitrator.arbitrate_divergence(divergence)
        assert outcome.resolved is False
        assert outcome.policy_applied == ConflictResolutionPolicy.HUMAN_IN_THE_LOOP
        assert outcome.requires_human_confirmation is True


class TestHandoffIntegrityPipeline:
    """Tests for cryptographic sealing and tampering prevention."""

    def test_seal_and_verify_valid_packet(self) -> None:
        pipeline = HandoffIntegrityPipeline(secret_salt="test-salt-secret")

        ast = MemoryAssertion(
            assertion_id="ast-1",
            subject="task_target",
            predicate="is",
            object_value="build_frontend",
            confidence=1.0,
            source_agent_id="coder",
        )

        packet = pipeline.seal_handoff(
            source_agent_id="coder",
            target_agent_id="tester",
            task_id="task_build_1",
            context_snapshot="Frontend built successfully with 0 lint errors.",
            assertions=[ast],
        )

        assert packet.packet_id.startswith("pkt-")
        assert len(packet.signature_sha256) == 64

        res = pipeline.verify_handoff(packet)
        assert res.is_valid is True
        assert res.verified_assertions_count == 1
        assert res.rejection_reason is None

    def test_detect_tampered_payload(self) -> None:
        pipeline = HandoffIntegrityPipeline(secret_salt="test-salt-secret")

        packet = pipeline.seal_handoff(
            source_agent_id="coder",
            target_agent_id="tester",
            task_id="task_1",
            context_snapshot="Original context",
        )

        # Simulate tampering
        tampered_packet = packet.model_copy(
            update={"context_snapshot": "Tampered malicious context"}
        )

        res = pipeline.verify_handoff(tampered_packet)
        assert res.is_valid is False
        assert res.rejection_reason is not None
        assert "Signature mismatch" in res.rejection_reason


class TestCrossAgentArbitrationTool:
    """Tests for LangChain tool execution."""

    def test_tool_execution(self, tmp_path: Path) -> None:
        test_file = tmp_path / "app_config.txt"
        test_file.write_text("cache_store=redis", encoding="utf-8")

        tool = create_cross_agent_arbitration_tool(workspace_root=tmp_path)

        result_str = tool.invoke(
            {
                "subject": "cache_store",
                "predicate": "uses",
                "my_value": "redis",
                "peer_value": "memcached",
                "my_agent_id": "agent_alpha",
                "peer_agent_id": "agent_beta",
                "my_confidence": 0.8,
                "peer_confidence": 0.8,
                "my_source_reference": "app_config.txt",
                "peer_source_reference": None,
                "workspace_root": str(tmp_path),
            }
        )

        payload = json.loads(result_str)
        assert payload["resolved"] is True
        assert payload["policy_applied"] == "ground_truth_first"
        assert payload["winning_assertion"]["object_value"] == "redis"
        assert payload["requires_human_confirmation"] is False
