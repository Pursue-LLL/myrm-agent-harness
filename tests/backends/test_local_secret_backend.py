"""Tests for LocalSecretBackend with atomic write support."""

import os
from unittest.mock import patch

import pytest

from myrm_agent_harness.backends.secrets.local_backend import (
    LocalSecretBackend,
    SecretEncryptionError,
)
from myrm_agent_harness.utils.crypto.exceptions import EncryptionError


@pytest.fixture
def backend(tmp_path: object) -> LocalSecretBackend:
    """Create a LocalSecretBackend with a temporary directory."""
    return LocalSecretBackend(master_key="test-master-key-32bytes!", base_dir=str(tmp_path))


@pytest.fixture
def tmp_path_str(tmp_path: object) -> str:
    return str(tmp_path)


class TestBasicOperations:
    def test_set_and_get_secret(self, backend: LocalSecretBackend) -> None:
        backend.set_secret("agent-1", "API_KEY", "sk-12345")
        assert backend.get_secret("agent-1", "API_KEY") == "sk-12345"

    def test_get_nonexistent_secret(self, backend: LocalSecretBackend) -> None:
        assert backend.get_secret("agent-1", "MISSING") is None

    def test_get_nonexistent_agent(self, backend: LocalSecretBackend) -> None:
        assert backend.get_secret("no-agent", "API_KEY") is None

    def test_delete_secret(self, backend: LocalSecretBackend) -> None:
        backend.set_secret("agent-1", "KEY", "value")
        assert backend.delete_secret("agent-1", "KEY") is True
        assert backend.get_secret("agent-1", "KEY") is None

    def test_delete_nonexistent_secret(self, backend: LocalSecretBackend) -> None:
        assert backend.delete_secret("agent-1", "MISSING") is False

    def test_get_all_secrets(self, backend: LocalSecretBackend) -> None:
        backend.set_secret("agent-1", "KEY_A", "val_a")
        backend.set_secret("agent-1", "KEY_B", "val_b")
        secrets = backend.get_all_secrets("agent-1")
        assert secrets == {"KEY_A": "val_a", "KEY_B": "val_b"}

    def test_delete_all_secrets(self, backend: LocalSecretBackend) -> None:
        backend.set_secret("agent-1", "KEY_A", "val_a")
        backend.set_secret("agent-1", "KEY_B", "val_b")
        backend.delete_all_secrets("agent-1")
        assert backend.get_all_secrets("agent-1") == {}

    def test_overwrite_secret(self, backend: LocalSecretBackend) -> None:
        backend.set_secret("agent-1", "KEY", "old")
        backend.set_secret("agent-1", "KEY", "new")
        assert backend.get_secret("agent-1", "KEY") == "new"

    def test_agent_isolation(self, backend: LocalSecretBackend) -> None:
        backend.set_secret("agent-1", "KEY", "val1")
        backend.set_secret("agent-2", "KEY", "val2")
        assert backend.get_secret("agent-1", "KEY") == "val1"
        assert backend.get_secret("agent-2", "KEY") == "val2"


class TestAtomicWrite:
    def test_no_temp_files_left(self, backend: LocalSecretBackend, tmp_path_str: str) -> None:
        """After write, no .tmp files should remain."""
        backend.set_secret("agent-1", "KEY", "value")
        agent_dir = os.path.join(tmp_path_str, "agent-1")
        files = os.listdir(agent_dir)
        assert all(not f.endswith(".tmp") for f in files), f"Temp files found: {files}"

    def test_original_file_preserved_on_encryption_error(self, backend: LocalSecretBackend) -> None:
        """If encryption fails, the original file should be untouched."""
        backend.set_secret("agent-1", "KEY", "original")

        with patch(
            "myrm_agent_harness.backends.secrets.local_backend.ConfigCrypto.encrypt_value",
            side_effect=EncryptionError("encryption boom"),
        ), pytest.raises(SecretEncryptionError):
            backend.set_secret("agent-1", "KEY", "corrupted")

        assert backend.get_secret("agent-1", "KEY") == "original"

    def test_write_creates_directory(self, tmp_path: object) -> None:
        """Writing to a non-existent agent directory should create it."""
        new_dir = os.path.join(str(tmp_path), "deep", "nested")
        backend = LocalSecretBackend(master_key="test-key-1234567890!", base_dir=new_dir)
        backend.set_secret("agent-new", "KEY", "value")
        assert backend.get_secret("agent-new", "KEY") == "value"

    def test_empty_secrets_removes_file(self, backend: LocalSecretBackend, tmp_path_str: str) -> None:
        """Deleting all secrets should remove the .secrets.enc file."""
        backend.set_secret("agent-1", "KEY", "value")
        file_path = os.path.join(tmp_path_str, "agent-1", ".secrets.enc")
        assert os.path.exists(file_path)

        backend.delete_secret("agent-1", "KEY")
        assert not os.path.exists(file_path)


class TestEdgeCases:
    def test_empty_master_key_raises(self) -> None:
        with pytest.raises(ValueError, match="master_key must be explicitly provided"):
            LocalSecretBackend(master_key="")

    def test_special_characters_in_value(self, backend: LocalSecretBackend) -> None:
        special = 'key with "quotes" & <angle> brackets\nand newlines'
        backend.set_secret("agent-1", "SPECIAL", special)
        assert backend.get_secret("agent-1", "SPECIAL") == special

    def test_unicode_value(self, backend: LocalSecretBackend) -> None:
        backend.set_secret("agent-1", "UNICODE", "密钥值")
        assert backend.get_secret("agent-1", "UNICODE") == "密钥值"
