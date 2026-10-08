"""Unit tests for Integration Egress Trust Lifecycle Suite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.integration_trust import (
    DisconnectPurgeReceipt,
    IntegrationLifecycleEngine,
    ProviderRevokeConfig,
    RevocationStatus,
)


@pytest.fixture
def lifecycle_engine() -> IntegrationLifecycleEngine:
    return IntegrationLifecycleEngine()


def test_preconnect_disclosure_card_lookup(lifecycle_engine: IntegrationLifecycleEngine) -> None:
    registry = lifecycle_engine.disclosure_registry

    # 1. Google Workspace disclosure
    gw = registry.get_disclosure("google_workspace")
    assert gw is not None
    assert gw.display_name == "Google Workspace (Gmail & Drive)"
    assert len(gw.data_types_read) > 0
    assert "Gmail" in gw.display_name
    assert "purge all synced email memory trees" in gw.purge_policy_summary

    # 2. GitHub disclosure
    gh = registry.get_disclosure("github")
    assert gh is not None
    assert any("Repository code" in d for d in gh.data_types_read)

    # 3. List disclosures
    all_disc = registry.list_disclosures()
    assert len(all_disc) >= 3


def test_atomic_disconnect_purge_on_disconnect(
    lifecycle_engine: IntegrationLifecycleEngine,
) -> None:
    purged_providers: list[str] = []

    def mock_purge(provider_id: str) -> tuple[int, int]:
        purged_providers.append(provider_id)
        # Cleared 3 memory trees and 42 documents
        return (3, 42)

    def mock_revoke(provider_id: str) -> tuple[RevocationStatus, str | None]:
        return (RevocationStatus.REVOKED_REMOTE, f"receipt_oauth_revoke_{provider_id}")

    receipt: DisconnectPurgeReceipt = lifecycle_engine.execute_atomic_disconnect(
        provider_id="google_workspace",
        purge_data_fn=mock_purge,
        remote_revoke_fn=mock_revoke,
        purge_synced_data=True,
    )

    assert receipt.provider_id == "google_workspace"
    assert receipt.cleared_memory_trees == 3
    assert receipt.cleared_documents == 42
    assert receipt.revocation_status == RevocationStatus.REVOKED_REMOTE
    assert receipt.revocation_receipt == "receipt_oauth_revoke_google_workspace"
    assert "google_workspace" in purged_providers
    assert receipt.timestamp != ""


def test_disconnect_with_purge_disabled(lifecycle_engine: IntegrationLifecycleEngine) -> None:
    purged_called = False

    def mock_purge(provider_id: str) -> tuple[int, int]:
        nonlocal purged_called
        purged_called = True
        return (5, 5)

    receipt = lifecycle_engine.execute_atomic_disconnect(
        provider_id="google_workspace",
        purge_data_fn=mock_purge,
        purge_synced_data=False,
    )

    assert not purged_called
    assert receipt.cleared_memory_trees == 0
    assert receipt.cleared_documents == 0
    assert receipt.revocation_status == RevocationStatus.REVOKED_REMOTE


def test_disconnect_unsupported_remote_revoke_with_manual_fallback() -> None:
    custom_configs = (
        ProviderRevokeConfig(
            provider_id="custom_service",
            revocation_endpoint=None,
            supports_remote_revoke=False,
            manual_revoke_url="https://custom.service.com/manage-apps",
        ),
    )
    engine = IntegrationLifecycleEngine(revoke_configs=custom_configs)

    receipt = engine.execute_atomic_disconnect(provider_id="custom_service")

    assert receipt.revocation_status == RevocationStatus.REVOKED_LOCAL_ONLY
    assert receipt.manual_revoke_url == "https://custom.service.com/manage-apps"
    assert receipt.revocation_receipt == "local_credential_deleted"
