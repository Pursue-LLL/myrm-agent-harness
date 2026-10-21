"""Tests for vault markdown write guard."""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.agent.meta_tools.file_ops.validators.markdown_vault_write_guard import (
    MarkdownVaultWriteGuard,
)


def test_apply_preserves_frontmatter_in_vault(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / ".obsidian").mkdir()
    note = vault / "daily.md"
    note.write_text("---\ndate: 2026-07-28\n---\n# Daily\n\nOld\n", encoding="utf-8")

    pre = note.read_text(encoding="utf-8")
    post = "# Daily\n\nUpdated journal\n"
    merged, warnings = MarkdownVaultWriteGuard.apply(str(note), pre, post)

    assert "date: 2026-07-28" in merged
    assert "Updated journal" in merged
    assert warnings


def test_apply_noop_outside_vault(tmp_path: Path) -> None:
    note = tmp_path / "readme.md"
    pre = "# Title\n"
    post = "# Title\n\nChanged\n"
    merged, warnings = MarkdownVaultWriteGuard.apply(str(note), pre, post)
    assert merged == post
    assert not warnings


def test_apply_preserves_frontmatter_when_post_body_cleared(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / ".obsidian").mkdir()
    note = vault / "note.md"

    pre = "---\ndate: 2026-07-28\n---\n# Title\n"
    post = ""
    merged, warnings = MarkdownVaultWriteGuard.apply(str(note), pre, post)
    assert "date: 2026-07-28" in merged
    assert warnings
