"""Unit tests for DirTrustGate suite."""

from pathlib import Path
import tempfile
import pytest

from myrm_agent_harness.core.security.dir_trust_gate import (
    DirTrustGate,
    DirectoryTrustStore,
    ProjectRemoteConfig,
)


@pytest.fixture
def temp_store(tmp_path: Path) -> DirectoryTrustStore:
    storage = tmp_path / "trusted.json"
    return DirectoryTrustStore(storage_path=storage)


def test_untrusted_directory_drops_remote_settings(
    temp_store: DirectoryTrustStore,
) -> None:
    gate = DirTrustGate(trust_store=temp_store)

    config = ProjectRemoteConfig(
        remote_url="https://malicious.evil.com/sync",
        remote_token="secret_token_123",
        scope="team-marketing",
    )

    result = gate.evaluate("/tmp/random-cloned-repo", config)

    assert result.is_trusted is False
    assert result.is_remote_allowed is False
    assert result.allowed_remote_url is None
    assert result.allowed_remote_token is None
    assert result.effective_scope == "team-marketing"
    assert result.warning_message is not None
    assert "Remote settings (URL/token) were dropped" in result.warning_message
    assert "Please authorize this workspace" in result.warning_message


def test_trusted_directory_honors_remote_settings(
    temp_store: DirectoryTrustStore,
) -> None:
    gate = DirTrustGate(trust_store=temp_store)
    test_dir = "/tmp/my-safe-repo"

    temp_store.trust(test_dir, reason="User explicitly ran trust")

    config = ProjectRemoteConfig(
        remote_url="https://plur.datafund.io",
        remote_token="valid_token_xyz",
        scope="enterprise",
    )

    result = gate.evaluate(test_dir, config)

    assert result.is_trusted is True
    assert result.is_remote_allowed is True
    assert result.allowed_remote_url == "https://plur.datafund.io"
    assert result.allowed_remote_token == "valid_token_xyz"
    assert result.effective_scope == "enterprise"
    assert result.warning_message is None


def test_untrusted_directory_without_remote_settings(
    temp_store: DirectoryTrustStore,
) -> None:
    gate = DirTrustGate(trust_store=temp_store)

    config = ProjectRemoteConfig(
        remote_url=None,
        remote_token=None,
        scope="local-project",
    )

    result = gate.evaluate("/tmp/local-only-repo", config)

    assert result.is_trusted is False
    assert result.is_remote_allowed is False
    assert result.allowed_remote_url is None
    assert result.allowed_remote_token is None
    assert result.effective_scope == "local-project"
    # No warning needed if no credentials were provided
    assert result.warning_message is None


def test_trust_and_untrust_lifecycle(temp_store: DirectoryTrustStore) -> None:
    test_dir = "/tmp/lifecycle-repo"
    assert temp_store.is_trusted(test_dir) is False

    canonical = temp_store.trust(test_dir)
    assert temp_store.is_trusted(test_dir) is True
    assert canonical in temp_store.list_trusted()

    untrusted = temp_store.untrust(test_dir)
    assert untrusted is True
    assert temp_store.is_trusted(test_dir) is False
    assert canonical not in temp_store.list_trusted()

    # Second untrust returns False
    assert temp_store.untrust(test_dir) is False


def test_symlink_path_canonicalization(tmp_path: Path) -> None:
    real_dir = tmp_path / "real_repo"
    real_dir.mkdir()
    symlink_dir = tmp_path / "symlink_repo"
    symlink_dir.symlink_to(real_dir)

    store = DirectoryTrustStore(storage_path=tmp_path / "trusted.json")
    gate = DirTrustGate(trust_store=store)

    # Trust via symlink
    store.trust(symlink_dir)

    # Verify both symlink and real dir evaluate as trusted
    assert store.is_trusted(real_dir) is True
    assert store.is_trusted(symlink_dir) is True

    config = ProjectRemoteConfig(remote_url="https://api.myrm.io", remote_token="tok1")
    eval_real = gate.evaluate(real_dir, config)
    assert eval_real.is_trusted is True
    assert eval_real.is_remote_allowed is True


def test_ancestor_directory_trust_inheritance(tmp_path: Path) -> None:
    parent_repo = tmp_path / "monorepo"
    parent_repo.mkdir()
    sub_package = parent_repo / "packages" / "frontend"
    sub_package.mkdir(parents=True)

    store = DirectoryTrustStore(storage_path=tmp_path / "trusted.json")
    gate = DirTrustGate(trust_store=store)

    # Initially untrusted
    assert store.is_trusted(sub_package) is False

    # Trust parent repo
    store.trust(parent_repo)

    # Direct match is False with allow_ancestor=False
    assert store.is_trusted(sub_package, allow_ancestor=False) is False
    # But inherits trust with allow_ancestor=True
    assert store.is_trusted(sub_package, allow_ancestor=True) is True

    # Gate evaluate automatically honors ancestor trust
    config = ProjectRemoteConfig(remote_url="https://api.myrm.io", remote_token="tok1")
    eval_sub = gate.evaluate(sub_package, config)
    assert eval_sub.is_trusted is True
    assert eval_sub.is_remote_allowed is True
