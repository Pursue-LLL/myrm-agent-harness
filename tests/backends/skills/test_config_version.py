"""Tests for skill config version persistence on MYRM_DATA_DIR."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.backends.skills.config_version import (
    bump_skill_config_version,
    get_skill_config_version,
)

_VERSION_FILENAME = ".skill_config_version"


@pytest.fixture
def version_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("MYRM_DATA_DIR", str(tmp_path))
    return tmp_path


def test_get_returns_zero_when_file_missing(version_dir: Path) -> None:
    assert get_skill_config_version() == 0.0


def test_bump_persists_and_get_reads(version_dir: Path) -> None:
    bump_skill_config_version()
    first = get_skill_config_version()
    assert first > 0.0

    bump_skill_config_version()
    second = get_skill_config_version()
    assert second >= first


def test_version_file_lives_under_myrm_data_dir(version_dir: Path) -> None:
    bump_skill_config_version()
    version_file = version_dir / _VERSION_FILENAME
    assert version_file.is_file()
    assert version_file.read_text(encoding="utf-8").strip()


def test_corrupt_version_file_returns_zero(version_dir: Path) -> None:
    version_file = version_dir / _VERSION_FILENAME
    version_file.write_text("not-a-float\n", encoding="utf-8")
    assert get_skill_config_version() == 0.0
