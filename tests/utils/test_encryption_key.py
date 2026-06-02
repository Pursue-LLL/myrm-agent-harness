"""Tests for encryption key resolution logic."""

import os
import stat
from pathlib import Path

import pytest

from myrm_agent_harness.utils.encryption_key import resolve_local_encryption_key


@pytest.fixture
def tmp_state_dir(tmp_path: Path) -> Path:
    """Provide a temp directory as state_dir."""
    return tmp_path / "state"


@pytest.fixture(autouse=True)
def clean_env():
    """Remove CONFIG_ENCRYPTION_KEY env var for test isolation."""
    original = os.environ.pop("CONFIG_ENCRYPTION_KEY", None)
    yield
    if original is not None:
        os.environ["CONFIG_ENCRYPTION_KEY"] = original
    else:
        os.environ.pop("CONFIG_ENCRYPTION_KEY", None)


class TestResolveFromEnvVar:
    def test_env_var_takes_priority(self, tmp_state_dir: Path):
        os.environ["CONFIG_ENCRYPTION_KEY"] = "my-secret-key"
        key = resolve_local_encryption_key(str(tmp_state_dir))
        assert len(key) == 32
        assert not (tmp_state_dir / ".encryption_key").exists()

    def test_env_var_deterministic(self, tmp_state_dir: Path):
        os.environ["CONFIG_ENCRYPTION_KEY"] = "stable-secret"
        key1 = resolve_local_encryption_key(str(tmp_state_dir))
        key2 = resolve_local_encryption_key(str(tmp_state_dir))
        assert key1 == key2


class TestResolveFromFile:
    def test_reads_existing_key_file(self, tmp_state_dir: Path):
        tmp_state_dir.mkdir(parents=True)
        key_file = tmp_state_dir / ".encryption_key"
        key_file.write_text("file-based-secret")

        key = resolve_local_encryption_key(str(tmp_state_dir))
        assert len(key) == 32

    def test_file_takes_priority_over_auto_generate(self, tmp_state_dir: Path):
        tmp_state_dir.mkdir(parents=True)
        key_file = tmp_state_dir / ".encryption_key"
        key_file.write_text("pre-existing-key")

        key1 = resolve_local_encryption_key(str(tmp_state_dir))
        key2 = resolve_local_encryption_key(str(tmp_state_dir))
        assert key1 == key2

    def test_empty_file_triggers_auto_generate(self, tmp_state_dir: Path):
        tmp_state_dir.mkdir(parents=True)
        key_file = tmp_state_dir / ".encryption_key"
        key_file.write_text("")

        key = resolve_local_encryption_key(str(tmp_state_dir))
        assert len(key) == 32
        assert key_file.read_text().strip() != ""


class TestAutoGenerate:
    def test_generates_key_when_nothing_exists(self, tmp_state_dir: Path):
        key = resolve_local_encryption_key(str(tmp_state_dir))
        assert len(key) == 32
        key_file = tmp_state_dir / ".encryption_key"
        assert key_file.exists()

    def test_generated_key_has_restricted_permissions(self, tmp_state_dir: Path):
        resolve_local_encryption_key(str(tmp_state_dir))
        key_file = tmp_state_dir / ".encryption_key"
        mode = key_file.stat().st_mode
        assert mode & stat.S_IRUSR
        assert mode & stat.S_IWUSR
        assert not (mode & stat.S_IRGRP)
        assert not (mode & stat.S_IROTH)

    def test_generated_key_is_stable_across_calls(self, tmp_state_dir: Path):
        key1 = resolve_local_encryption_key(str(tmp_state_dir))
        key2 = resolve_local_encryption_key(str(tmp_state_dir))
        assert key1 == key2

    def test_creates_parent_directories(self, tmp_state_dir: Path):
        nested = tmp_state_dir / "deep" / "nested"
        key = resolve_local_encryption_key(str(nested))
        assert len(key) == 32
        assert (nested / ".encryption_key").exists()


class TestPriorityOrder:
    def test_env_var_overrides_file(self, tmp_state_dir: Path):
        tmp_state_dir.mkdir(parents=True)
        (tmp_state_dir / ".encryption_key").write_text("file-key")
        os.environ["CONFIG_ENCRYPTION_KEY"] = "env-key"

        key_from_env = resolve_local_encryption_key(str(tmp_state_dir))

        del os.environ["CONFIG_ENCRYPTION_KEY"]
        key_from_file = resolve_local_encryption_key(str(tmp_state_dir))

        assert key_from_env != key_from_file
