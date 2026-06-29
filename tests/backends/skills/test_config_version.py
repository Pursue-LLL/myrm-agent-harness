"""Tests for skill config version persistence on MYRM_DATA_DIR."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.backends.skills import config_version


@pytest.fixture
def version_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("MYRM_DATA_DIR", str(tmp_path))
    return tmp_path


def test_get_returns_zero_when_file_missing(version_dir: Path) -> None:
    assert config_version.get_skill_config_version() == 0.0


def test_bump_persists_and_get_reads(version_dir: Path) -> None:
    config_version.bump_skill_config_version()
    first = config_version.get_skill_config_version()
    assert first > 0.0

    config_version.bump_skill_config_version()
    second = config_version.get_skill_config_version()
    assert second >= first


def test_version_file_lives_under_myrm_data_dir(version_dir: Path) -> None:
    config_version.bump_skill_config_version()
    version_file = version_dir / ".skill_config_version"
    assert version_file.is_file()
    assert version_file.read_text(encoding="utf-8").strip()
