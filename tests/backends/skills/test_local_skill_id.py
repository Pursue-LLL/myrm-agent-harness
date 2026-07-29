"""Tests for canonical local skill IDs."""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.backends.skills.local_skill_id import (
    local_skill_id_from_path,
    resolve_local_install_dir,
)


def test_local_skill_id_is_stable_for_same_path(tmp_path: Path) -> None:
    skill_dir = tmp_path / "demo-skill"
    skill_dir.mkdir()
    first = local_skill_id_from_path(skill_dir)
    second = local_skill_id_from_path(skill_dir)
    assert first == second
    assert first.startswith("local::")
    assert len(first.removeprefix("local::")) == 16


def test_resolve_local_install_dir_by_hash_id(tmp_path: Path) -> None:
    skill_dir = tmp_path / "demo-skill"
    skill_dir.mkdir()
    skill_id = local_skill_id_from_path(skill_dir)

    resolved = resolve_local_install_dir(skill_id, tmp_path)
    assert resolved == skill_dir


def test_resolve_local_install_dir_returns_none_for_unknown_hash(
    tmp_path: Path,
) -> None:
    resolved = resolve_local_install_dir("local::0123456789abcdef", tmp_path)
    assert resolved is None
