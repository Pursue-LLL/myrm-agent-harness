"""Tests for wiki vault local git snapshots."""

from __future__ import annotations

import shutil

import pytest

from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.portability.vault_git import (
    commit_vault_git_snapshot,
    maybe_commit_vault_git_snapshot,
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")


@pytest.fixture
def temp_vault(tmp_path) -> WikiStructure:
    structure = WikiStructure(tmp_path / "agent-vault")
    structure.ensure_structure()
    return structure


def test_commit_vault_git_snapshot_initializes_repo(temp_vault: WikiStructure) -> None:
    concept_path = temp_vault.get_concept_file_path("AI/Test")
    concept_path.write_text("---\ntype: concept\n---\n\n# Test\n", encoding="utf-8")

    result = commit_vault_git_snapshot(temp_vault, reason="compile")
    assert result.committed is True
    assert result.commit_hash is not None
    assert len(result.commit_hash) == 40
    assert (temp_vault.base_dir / ".git").is_dir()
    assert (temp_vault.base_dir / ".gitignore").is_file()


def test_commit_vault_git_snapshot_skips_without_changes(temp_vault: WikiStructure) -> None:
    concept_path = temp_vault.get_concept_file_path("AI/Test")
    concept_path.write_text("---\ntype: concept\n---\n\n# Test\n", encoding="utf-8")

    first = commit_vault_git_snapshot(temp_vault, reason="compile")
    second = commit_vault_git_snapshot(temp_vault, reason="compile")

    assert first.committed is True
    assert second.committed is False
    assert second.skipped_reason == "no_changes"


def test_maybe_commit_vault_git_snapshot_respects_config(temp_vault: WikiStructure) -> None:
    concept_path = temp_vault.get_concept_file_path("AI/Test")
    concept_path.write_text("---\ntype: concept\n---\n\n# Test\n", encoding="utf-8")

    disabled = WikiConfig(enable_version_control=False)
    result = maybe_commit_vault_git_snapshot(temp_vault, disabled, reason="compile")
    assert result.committed is False
    assert result.skipped_reason == "disabled"
    assert not (temp_vault.base_dir / ".git").exists()

    enabled = WikiConfig(enable_version_control=True)
    committed = maybe_commit_vault_git_snapshot(temp_vault, enabled, reason="compile")
    assert committed.committed is True
