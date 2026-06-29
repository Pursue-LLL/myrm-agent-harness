"""Tests for skill config version persistence on MYRM_DATA_DIR."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from myrm_agent_harness.backends.skills import config_version as config_version_module
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


def test_corrupt_version_file_returns_zero(version_dir: Path, caplog: pytest.LogCaptureFixture) -> None:
    version_file = version_dir / _VERSION_FILENAME
    version_file.write_text("not-a-float\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert get_skill_config_version() == 0.0
    assert any("Invalid skill config version" in record.message for record in caplog.records)


def test_empty_version_file_returns_zero(version_dir: Path) -> None:
    version_file = version_dir / _VERSION_FILENAME
    version_file.write_text("   \n", encoding="utf-8")
    assert get_skill_config_version() == 0.0


def test_read_oserror_logs_warning_and_returns_zero(
    version_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    version_file = version_dir / _VERSION_FILENAME
    version_file.write_text("1.0\n", encoding="utf-8")

    def _raise_oserror(self: Path, *args: object, **kwargs: object) -> str:
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "read_text", _raise_oserror)
    with caplog.at_level(logging.WARNING):
        assert get_skill_config_version() == 0.0
    assert any("Failed to read skill config version file" in record.message for record in caplog.records)


def test_default_myrm_data_dir_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("MYRM_DATA_DIR", raising=False)
    monkeypatch.setattr(config_version_module.Path, "home", lambda: tmp_path)
    bump_skill_config_version()
    version_file = tmp_path / ".myrm" / _VERSION_FILENAME
    assert version_file.is_file()
    assert get_skill_config_version() > 0.0
