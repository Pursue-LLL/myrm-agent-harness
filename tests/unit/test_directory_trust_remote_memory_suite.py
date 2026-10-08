"""Unit tests for DirectoryTrustStore and SinglePointRemoteMemoryResolver."""

from __future__ import annotations

import os
import tempfile

from myrm_agent_harness.core.security.directory_trust_remote_memory import (
    DirectoryTrustStore,
    ProjectMemoryConfig,
    SinglePointRemoteMemoryResolver,
    TrustStatus,
)


def test_directory_trust_store_hierarchy_and_canonicalization() -> None:
    store = DirectoryTrustStore()
    with tempfile.TemporaryDirectory() as tmpdir:
        sub_dir = os.path.join(tmpdir, "subdir", "nested")
        os.makedirs(sub_dir, exist_ok=True)

        assert store.is_directory_trusted(tmpdir) is False
        assert store.is_directory_trusted(sub_dir) is False

        # Trust root
        store.trust_directory(tmpdir)
        assert store.is_directory_trusted(tmpdir) is True
        # Subdirectory matches parent root
        assert store.is_directory_trusted(sub_dir) is True

        # Untrust root
        store.untrust_directory(tmpdir)
        assert store.is_directory_trusted(tmpdir) is False
        assert store.is_directory_trusted(sub_dir) is False


def test_resolver_local_scope_only_untrusted_allowed() -> None:
    store = DirectoryTrustStore()
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_path = os.path.join(tmpdir, ".myrm.yaml")
        cfg = ProjectMemoryConfig(
            local_scope="scope-frontend-team",
            domain="frontend",
            remote_url=None,
            remote_token=None,
        )

        res = SinglePointRemoteMemoryResolver.resolve_from_config(
            config=cfg,
            config_path=cfg_path,
            trust_store=store,
        )

        assert res.is_trusted is False
        assert res.trust_status == TrustStatus.UNTRUSTED
        assert res.is_outbound_authorized is False
        assert res.remote_memory is None
        assert res.effective_scope == "scope-frontend-team"
        assert res.refused_from is None
        assert res.refusal_notice is None


def test_resolver_remote_memory_gated_by_directory_trust() -> None:
    store = DirectoryTrustStore()
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_path = os.path.join(tmpdir, ".myrm.yaml")
        cfg = ProjectMemoryConfig(
            local_scope="scope-finance",
            remote_url="https://remote-mem.corp.example.com",
            remote_token="token-secret-12345",
            remote_scopes=["enterprise/finance"],
        )

        # 1. Untrusted directory: remote memory MUST be refused
        res_blocked = SinglePointRemoteMemoryResolver.resolve_from_config(
            config=cfg,
            config_path=cfg_path,
            trust_store=store,
        )

        assert res_blocked.is_trusted is False
        assert res_blocked.is_outbound_authorized is False
        assert res_blocked.remote_memory is None
        assert res_blocked.refused_from is not None
        assert res_blocked.refusal_notice is not None
        assert "[MYRM] Ignored remote memory settings" in res_blocked.refusal_notice
        assert "myrm trust" in res_blocked.refusal_notice
        assert res_blocked.effective_scope == "scope-finance"

        # 2. Explicitly trust directory: remote memory authorized
        store.trust_directory(tmpdir)
        res_allowed = SinglePointRemoteMemoryResolver.resolve_from_config(
            config=cfg,
            config_path=cfg_path,
            trust_store=store,
        )

        assert res_allowed.is_trusted is True
        assert res_allowed.trust_status == TrustStatus.TRUSTED
        assert res_allowed.is_outbound_authorized is True
        assert res_allowed.remote_memory is not None
        assert res_allowed.remote_memory.url == "https://remote-mem.corp.example.com"
        assert res_allowed.remote_memory.token == "token-secret-12345"
        assert res_allowed.remote_memory.scopes == ["enterprise/finance"]
        assert res_allowed.refused_from is None
        assert res_allowed.refusal_notice is None
