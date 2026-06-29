"""Unit tests for workspace artifact vault path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.agent.artifacts.vault import ArtifactVault
from myrm_agent_harness.core.artifacts.paths import (
    ARTIFACT_VAULT_DIR_NAME,
    WORKSPACE_AGENT_DIR_NAME,
    resolve_workspace_artifact_vault_dir,
    workspace_vault_relative_parts,
)


def test_default_vault_dir_under_agent(tmp_path: Path) -> None:
    assert resolve_workspace_artifact_vault_dir(tmp_path) == tmp_path / ".agent" / "vault"
    assert workspace_vault_relative_parts() == (WORKSPACE_AGENT_DIR_NAME, ARTIFACT_VAULT_DIR_NAME)


def test_artifact_vault_uses_same_vault_dir(tmp_path: Path) -> None:
    vault = ArtifactVault(str(tmp_path))
    assert vault.vault_dir == resolve_workspace_artifact_vault_dir(tmp_path)


def test_env_override_custom_relative_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENT_WORKSPACE_VAULT_RELATIVE", "runtime/vault")
    assert resolve_workspace_artifact_vault_dir(tmp_path) == tmp_path / "runtime" / "vault"
    assert workspace_vault_relative_parts() == ("runtime", "vault")


@pytest.mark.parametrize(
    "override",
    [
        "..",
        "foo/../bar",
        "/abs/path",
    ],
)
def test_env_override_rejects_unsafe_paths(
    override: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENT_WORKSPACE_VAULT_RELATIVE", override)
    with pytest.raises(ValueError):
        workspace_vault_relative_parts()


def test_whitespace_only_env_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_WORKSPACE_VAULT_RELATIVE", "   ")
    assert workspace_vault_relative_parts() == (WORKSPACE_AGENT_DIR_NAME, ARTIFACT_VAULT_DIR_NAME)


def test_context_bundle_facade_vault_dir_matches_ssot(tmp_path: Path) -> None:
    from myrm_agent_harness.toolkits.context_bundle import ContextBundleFacade

    facade = ContextBundleFacade.from_state_dir(tmp_path, ensure_layout=False)
    assert facade.vault_dir(tmp_path) == resolve_workspace_artifact_vault_dir(tmp_path)
