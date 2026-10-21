"""Unit tests for Hybrid Cloud-Edge Sandbox Relay & Artifact Sync (Item 58)."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.sub_agents.cloud_edge_relay import (
    CloudEdgeEgressRelayCoordinator,
    HybridArtifactSyncEngine,
    NetworkEgressStatusEnum,
    RelayNodeRoleEnum,
)


class TestHybridArtifactSyncEngine:
    """Test suite for CAS-versioned bidirectional artifact incremental append."""

    def test_register_artifact_with_initial_baseline(self) -> None:
        engine = HybridArtifactSyncEngine()
        initial_csv = "id,name,status\n1,alpha,active\n2,beta,pending"
        state = engine.register_artifact(
            artifact_id="art-table-01",
            name="Feishu Multi-Grid Table",
            initial_content=initial_csv,
            initial_rows=3,
            author_role=RelayNodeRoleEnum.LOCAL_SANDBOX,
        )

        assert state.artifact_id == "art-table-01"
        assert state.name == "Feishu Multi-Grid Table"
        assert state.current_version == 1
        assert state.total_rows == 3
        assert len(state.chunks) == 1
        assert state.chunks[0].author_role == RelayNodeRoleEnum.LOCAL_SANDBOX
        assert state.chunks[0].checksum != ""

    def test_bidirectional_append_aligns_with_doubao_14_rows_scenario(self) -> None:
        """Simulates local engineer writing half table, then cloud sandbox appending 14 new records at night."""
        engine = HybridArtifactSyncEngine()

        # Step 1: Local writes initial base rows
        engine.register_artifact(
            artifact_id="art-leads-01",
            name="Overseas Leads",
            initial_content="Lead-01\nLead-02",
            initial_rows=2,
            author_role=RelayNodeRoleEnum.LOCAL_SANDBOX,
        )

        # Step 2: Cloud sandbox appends 14 rows overnight with CAS check
        cloud_delta = "\n".join(f"Cloud-Lead-{i:02d}" for i in range(1, 15))
        state_v2 = engine.append_chunk(
            artifact_id="art-leads-01",
            content_delta=cloud_delta,
            author_role=RelayNodeRoleEnum.CLOUD_SANDBOX,
            expected_version=1,
            row_count=14,
        )

        assert state_v2.current_version == 2
        assert state_v2.total_rows == 16  # 2 original + 14 appended
        assert len(state_v2.chunks) == 2
        assert state_v2.chunks[1].author_role == RelayNodeRoleEnum.CLOUD_SANDBOX
        assert state_v2.chunks[1].row_count == 14

        # Step 3: Local reviews and appends note
        state_v3 = engine.append_chunk(
            artifact_id="art-leads-01",
            content_delta="Local-Audit-Done",
            author_role=RelayNodeRoleEnum.LOCAL_SANDBOX,
            expected_version=2,
            row_count=1,
        )
        assert state_v3.current_version == 3
        assert state_v3.total_rows == 17

        # Step 4: Verify full content aggregation
        full_text = engine.get_aggregated_content("art-leads-01")
        assert "Lead-01" in full_text
        assert "Cloud-Lead-14" in full_text
        assert "Local-Audit-Done" in full_text

        # Step 5: Verify provenance timeline
        timeline = engine.get_provenance_summary("art-leads-01")
        assert len(timeline) == 3
        assert timeline[0]["author_role"] == "local_sandbox"
        assert timeline[1]["author_role"] == "cloud_sandbox"
        assert timeline[2]["author_role"] == "local_sandbox"

    def test_cas_version_conflict_prevention(self) -> None:
        engine = HybridArtifactSyncEngine()
        engine.register_artifact(
            artifact_id="art-conflict-01",
            name="Conflicting Document",
            initial_content="Line 1",
            initial_rows=1,
        )

        # Try to append with wrong expected_version
        with pytest.raises(ValueError, match="CAS version conflict"):
            engine.append_chunk(
                artifact_id="art-conflict-01",
                content_delta="Conflict line",
                author_role=RelayNodeRoleEnum.CLOUD_SANDBOX,
                expected_version=99,
            )

    def test_nonexistent_artifact_raises_key_error(self) -> None:
        engine = HybridArtifactSyncEngine()
        with pytest.raises(KeyError, match="not found"):
            engine.get_artifact_state("unknown-id")


class TestCloudEdgeEgressRelayCoordinator:
    """Test suite for SSRF-safe local network partition egress fetch relay."""

    def test_ssrf_disallowed_hosts_blocked(self) -> None:
        coord = CloudEdgeEgressRelayCoordinator()

        # Intranet / private IP targets
        with pytest.raises(ValueError, match="disallowed for egress relay"):
            coord.validate_target_url("http://127.0.0.1:8080/secret")

        with pytest.raises(ValueError, match="disallowed for egress relay"):
            coord.validate_target_url("https://localhost/admin")

        with pytest.raises(ValueError, match="disallowed for egress relay"):
            coord.validate_target_url("http://169.254.169.254/latest/meta-data/")

        with pytest.raises(ValueError, match="disallowed for egress relay"):
            coord.validate_target_url("http://192.168.1.1/router")

        # Invalid scheme
        with pytest.raises(ValueError, match="Invalid URL scheme"):
            coord.validate_target_url("ftp://example.com/file")

    def test_legitimate_relay_lifecycle(self) -> None:
        coord = CloudEdgeEgressRelayCoordinator(default_timeout_seconds=20.0)

        # 1. Cloud requests local egress to fetch restricted external source
        req = coord.create_relay_request(
            target_url="https://api.github.com/repos/sample/info",
            intent="Fetch latest release metadata blocked on cloud firewall",
            headers={"User-Agent": "Myrm-Relay/1.0"},
            timeout_seconds=10.0,
        )
        assert req.target_url == "https://api.github.com/repos/sample/info"
        assert req.source_node == RelayNodeRoleEnum.CLOUD_SANDBOX
        assert len(coord.list_pending_relays()) == 1

        # 2. Local node completes egress fetch and returns structured payload
        resp = coord.complete_relay_request(
            relay_id=req.relay_id,
            status=NetworkEgressStatusEnum.RELAY_COMPLETED,
            extracted_data='{"tag_name": "v1.4.0", "published_at": "2026-08-24"}',
            status_code=200,
            latency_ms=145.2,
        )
        assert resp.status == NetworkEgressStatusEnum.RELAY_COMPLETED
        assert resp.status_code == 200
        assert "v1.4.0" in resp.extracted_data
        assert len(coord.list_pending_relays()) == 0
        assert len(coord.list_completed_relays()) == 1

        # 3. Cloud reads the completed response
        fetched = coord.get_relay_response(req.relay_id)
        assert fetched is not None
        assert fetched.extracted_data == resp.extracted_data

    def test_completing_unknown_relay_raises_key_error(self) -> None:
        coord = CloudEdgeEgressRelayCoordinator()
        with pytest.raises(KeyError, match="not in pending queue"):
            coord.complete_relay_request(
                relay_id="nonexistent-relay",
                status=NetworkEgressStatusEnum.RELAY_FAILED,
                extracted_data="",
            )
