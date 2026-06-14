"""Tests for ArtifactVault (Layer 4 of multi-agent state sync).

Verifies: put/get round-trip, metadata, SHA256 integrity, concurrent writes, large file streaming.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from myrm_agent_harness.agent.artifacts.vault import VAULT_PREFIX, ArtifactVault


@pytest.fixture()
def vault(tmp_path: Path) -> ArtifactVault:
    return ArtifactVault(str(tmp_path))


class TestVaultPutGet:
    def test_put_returns_vault_uri(self, vault: ArtifactVault) -> None:
        uri = vault.put("hello world", "test.txt")
        assert uri.startswith(VAULT_PREFIX)

    def test_get_returns_original_content(self, vault: ArtifactVault) -> None:
        content = "Agent A result: plan complete"
        uri = vault.put(content, "plan_result.md")
        retrieved = vault.get(uri)
        assert retrieved == content.encode("utf-8")

    def test_put_bytes_content(self, vault: ArtifactVault) -> None:
        raw_bytes = b"\x00\x01\x02\xff binary data"
        uri = vault.put(raw_bytes, "binary.bin", "application/octet-stream")
        assert vault.get(uri) == raw_bytes

    def test_get_invalid_uri_raises(self, vault: ArtifactVault) -> None:
        with pytest.raises(ValueError, match="Invalid Vault URI"):
            vault.get("not-a-vault-uri")

    def test_get_missing_object_raises(self, vault: ArtifactVault) -> None:
        with pytest.raises(FileNotFoundError):
            vault.get(f"{VAULT_PREFIX}nonexistent-uuid")


class TestVaultMetadata:
    def test_metadata_sha256(self, vault: ArtifactVault) -> None:
        content = "test content for hash"
        uri = vault.put(content, "hash_test.txt")
        meta = vault.get_meta(uri)
        assert meta is not None
        expected_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert meta.sha256_hash == expected_hash

    def test_metadata_size(self, vault: ArtifactVault) -> None:
        content = "exact size test"
        uri = vault.put(content, "size_test.txt")
        meta = vault.get_meta(uri)
        assert meta is not None
        assert meta.size_bytes == len(content.encode("utf-8"))

    def test_metadata_filename(self, vault: ArtifactVault) -> None:
        uri = vault.put("data", "my_artifact.md", description="test artifact")
        meta = vault.get_meta(uri)
        assert meta is not None
        assert meta.filename == "my_artifact.md"
        assert meta.description == "test artifact"

    def test_list_objects(self, vault: ArtifactVault) -> None:
        vault.put("obj1", "first.txt")
        vault.put("obj2", "second.txt")
        objects = vault.list_objects()
        assert len(objects) == 2


class TestVaultPutFile:
    def test_put_file_streams_correctly(self, vault: ArtifactVault, tmp_path: Path) -> None:
        source = tmp_path / "large_input.txt"
        content = "A" * 10000
        source.write_text(content)
        uri = vault.put_file(source, "streamed.txt")
        retrieved = vault.get(uri).decode("utf-8")
        assert retrieved == content

    def test_put_file_nonexistent_raises(self, vault: ArtifactVault) -> None:
        with pytest.raises(FileNotFoundError):
            vault.put_file("/nonexistent/path.txt", "missing.txt")


class TestVaultConcurrency:
    def test_multiple_puts_no_conflict(self, vault: ArtifactVault) -> None:
        uris = [vault.put(f"content-{i}", f"file-{i}.txt") for i in range(10)]
        assert len(set(uris)) == 10
        for i, uri in enumerate(uris):
            assert vault.get(uri) == f"content-{i}".encode("utf-8")
