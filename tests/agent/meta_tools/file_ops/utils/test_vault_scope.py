"""Tests for vault scope detection."""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.agent.meta_tools.file_ops.utils.vault_scope import (
    find_vault_root,
    is_vault_markdown_path,
)


def test_find_vault_root_detects_obsidian_dir(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    notes = vault / "daily"
    notes.mkdir(parents=True)
    (vault / ".obsidian").mkdir()

    assert find_vault_root(str(notes / "note.md")) == vault.resolve()


def test_is_vault_markdown_path_true_for_vault_note(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / ".obsidian").mkdir()
    note = vault / "note.md"
    note.write_text("# hi", encoding="utf-8")

    assert is_vault_markdown_path(str(note)) is True


def test_is_vault_markdown_path_false_outside_vault(tmp_path: Path) -> None:
    note = tmp_path / "readme.md"
    note.write_text("# hi", encoding="utf-8")

    assert is_vault_markdown_path(str(note)) is False
