"""Tests for StorageVaultBackend (cloud-native storage backend) and
SessionVault edge branches (oversized cache entry, save/list/cleanup failures)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.browser.session_vault import SessionVault
from myrm_agent_harness.toolkits.browser.session_vault.backends import FileVaultBackend
from myrm_agent_harness.toolkits.browser.session_vault.backends.storage_backend import (
    StorageVaultBackend,
)
from myrm_agent_harness.toolkits.browser.session_vault.exceptions import (
    EncryptionError,
    InvalidDomainError,
)
from myrm_agent_harness.toolkits.browser.session_vault.types import (
    SessionEntry,
    SessionSummary,
    VaultMetrics,
)


class FakeStorageProvider:
    """In-memory StorageProvider stand-in (duck-typed, StorageVaultBackend only
    references StorageProvider under TYPE_CHECKING)."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.list_result: list[str] | None = None
        self.raise_on_list = False
        self.raise_on_write = False

    async def read(self, key: str) -> bytes:
        if key not in self.store:
            raise FileNotFoundError(key)
        return self.store[key]

    async def write(self, key: str, content: bytes, content_type: str | None = None) -> None:
        if self.raise_on_write:
            raise OSError("disk full")
        self.store[key] = content

    async def delete(self, key: str) -> None:
        if key not in self.store:
            raise FileNotFoundError(key)
        del self.store[key]

    async def list(self, prefix: str = "", recursive: bool = True) -> list[str]:
        if self.raise_on_list:
            raise RuntimeError("provider unavailable")
        if self.list_result is not None:
            return self.list_result
        return [
            key
            for key in self.store
            if key.startswith(prefix)
        ]


@pytest.fixture
def provider() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
def storage_backend(provider: FakeStorageProvider) -> StorageVaultBackend:
    return StorageVaultBackend(provider, prefix="browser/sessions")


@pytest.fixture
def vault_key() -> bytes:
    return os.urandom(32)


# =============================================================================
# StorageVaultBackend
# =============================================================================


class TestStorageVaultBackend:
    def test_init_rsplit_prefix(self, provider: FakeStorageProvider) -> None:
        backend = StorageVaultBackend(provider, prefix="browser/sessions/")
        assert backend._prefix == "browser/sessions"

    def test_storage_key_valid_domain(self, storage_backend: StorageVaultBackend) -> None:
        assert storage_backend._storage_key("example.com") == "browser/sessions/example.com.enc"

    def test_storage_key_url_encodes_special_chars(
        self, storage_backend: StorageVaultBackend
    ) -> None:
        assert storage_backend._storage_key("localhost:8080") == "browser/sessions/localhost%3A8080.enc"

    def test_storage_key_invalid_domain(self, storage_backend: StorageVaultBackend) -> None:
        with pytest.raises(InvalidDomainError):
            storage_backend._storage_key("a/../b")

    async def test_read_existing(
        self, storage_backend: StorageVaultBackend, provider: FakeStorageProvider
    ) -> None:
        provider.store["browser/sessions/example.com.enc"] = b"secret"
        assert await storage_backend.read("example.com") == b"secret"

    async def test_read_missing_returns_none(
        self, storage_backend: StorageVaultBackend
    ) -> None:
        assert await storage_backend.read("nope.com") is None

    async def test_write(
        self, storage_backend: StorageVaultBackend, provider: FakeStorageProvider
    ) -> None:
        await storage_backend.write("example.com", b"data")
        assert provider.store["browser/sessions/example.com.enc"] == b"data"

    async def test_delete_existing(
        self, storage_backend: StorageVaultBackend, provider: FakeStorageProvider
    ) -> None:
        provider.store["browser/sessions/example.com.enc"] = b"data"
        assert await storage_backend.delete("example.com") is True
        assert "browser/sessions/example.com.enc" not in provider.store

    async def test_delete_missing_returns_false(
        self, storage_backend: StorageVaultBackend
    ) -> None:
        assert await storage_backend.delete("nope.com") is False

    async def test_list_all_decodes_domains(
        self, storage_backend: StorageVaultBackend, provider: FakeStorageProvider
    ) -> None:
        provider.store["browser/sessions/example.com.enc"] = b"a"
        provider.store["browser/sessions/localhost%3A8080.enc"] = b"b"
        assert sorted(await storage_backend.list_all()) == ["example.com", "localhost:8080"]

    async def test_list_all_skips_invalid_keys(
        self, storage_backend: StorageVaultBackend, provider: FakeStorageProvider
    ) -> None:
        provider.list_result = [
            "browser/sessions/example.com.enc",
            "other/prefix/ignored.enc",
            "browser/sessions/missing-extension",
        ]
        assert await storage_backend.list_all() == ["example.com"]

    async def test_list_all_provider_error_returns_empty(
        self, storage_backend: StorageVaultBackend, provider: FakeStorageProvider
    ) -> None:
        provider.raise_on_list = True
        assert await storage_backend.list_all() == []

    async def test_list_all_unquote_error_skipped(
        self, storage_backend: StorageVaultBackend, provider: FakeStorageProvider
    ) -> None:
        provider.list_result = ["browser/sessions/bad.enc"]
        with patch(
            "myrm_agent_harness.toolkits.browser.session_vault.backends.storage_backend.unquote",
            side_effect=ValueError("bad url"),
        ):
            assert await storage_backend.list_all() == []

    async def test_backup_corrupted(
        self, storage_backend: StorageVaultBackend, provider: FakeStorageProvider
    ) -> None:
        await storage_backend.backup_corrupted("example.com", b"corrupt")
        assert provider.store["browser/sessions/example.com.corrupted"] == b"corrupt"

    async def test_backup_corrupted_error_swallowed(
        self, storage_backend: StorageVaultBackend, provider: FakeStorageProvider
    ) -> None:
        provider.raise_on_write = True
        await storage_backend.backup_corrupted("example.com", b"corrupt")


# =============================================================================
# SessionVault edge branches
# =============================================================================


class TestSessionVaultEdgeBranches:
    async def test_cache_put_skips_oversized_entry(
        self, tmp_path: Path, vault_key: bytes
    ) -> None:
        vault = SessionVault(
            FileVaultBackend(tmp_path), vault_key, cache_max_memory_mb=1
        )
        with patch.object(
            SessionVault, "_estimate_entry_size", return_value=10**7
        ):
            await vault.save("big.com", {"cookies": [{"name": "x"}]})
        assert "big.com" not in vault._cache

    async def test_cache_put_updates_existing_entry(
        self, tmp_path: Path, vault_key: bytes
    ) -> None:
        vault = SessionVault(FileVaultBackend(tmp_path), vault_key)
        await vault.save("example.com", {"cookies": [{"name": "a"}]})
        first_size = vault._cache["example.com"][2]
        await vault.save("example.com", {"cookies": [{"name": "a"}, {"name": "b"}]})
        assert vault._cache["example.com"][0].storage_state == {
            "cookies": [{"name": "a"}, {"name": "b"}]
        }
        assert vault._cache["example.com"][2] != first_size

    async def test_save_serialization_failure(
        self, tmp_path: Path, vault_key: bytes
    ) -> None:
        vault = SessionVault(FileVaultBackend(tmp_path), vault_key)
        with pytest.raises(ValueError):
            await vault.save("example.com", {"unserializable": object()})

    async def test_save_backend_failure(self, tmp_path: Path, vault_key: bytes) -> None:
        backend = FileVaultBackend(tmp_path)
        vault = SessionVault(backend, vault_key)
        with (
            patch.object(backend, "write", side_effect=OSError("disk full")),
            pytest.raises(OSError),
        ):
            await vault.save("example.com", {"cookies": []})

    async def test_encrypt_failure(self, tmp_path: Path, vault_key: bytes) -> None:
        vault = SessionVault(FileVaultBackend(tmp_path), vault_key)
        with (
            patch.object(
                type(vault._get_cipher()), "encrypt", side_effect=Exception("cipher boom")
            ),
            pytest.raises(EncryptionError),
        ):
            await vault.save("example.com", {"cookies": []})

    async def test_list_summaries_returns_metadata(
        self, tmp_path: Path, vault_key: bytes
    ) -> None:
        backend = FileVaultBackend(tmp_path)
        vault = SessionVault(backend, vault_key)
        await vault.save(
            "example.com",
            {"cookies": [{"name": "sid"}], "origins": [{"localStorage": [["k", "v"]]}]},
        )
        summaries = await vault.list_summaries()
        assert len(summaries) == 1
        assert summaries[0].domain == "example.com"
        assert summaries[0].cookie_count == 1
        assert summaries[0].local_storage_count == 1

    async def test_list_summaries_skips_corrupted(
        self, tmp_path: Path, vault_key: bytes
    ) -> None:
        backend = FileVaultBackend(tmp_path)
        vault = SessionVault(backend, vault_key)
        await vault.save("good.com", {"cookies": []})
        corrupt = (tmp_path / "bad.com.enc")
        corrupt.write_bytes(b"\x00\x01not-encrypted")
        summaries = await vault.list_summaries()
        assert [s.domain for s in summaries] == ["good.com"]

    async def test_cleanup_expired_removed_count(
        self, tmp_path: Path, vault_key: bytes
    ) -> None:
        backend = FileVaultBackend(tmp_path)
        vault = SessionVault(backend, vault_key)
        await vault.save("expired.com", {"cookies": []}, ttl_days=-1)
        await vault.save("alive.com", {"cookies": []}, ttl_days=30)
        removed = await vault.cleanup_expired()
        assert removed == 1
        assert "alive.com" in await backend.list_all()

    async def test_load_singleflight_waiter_recovers(
        self, tmp_path: Path, vault_key: bytes
    ) -> None:
        vault = SessionVault(FileVaultBackend(tmp_path), vault_key)
        # Pre-seed an in-flight future that already failed: the next load() acts
        # as the waiter, catches the exception, and falls through to retry.
        future: asyncio.Future[object] = asyncio.Future()
        future.set_exception(RuntimeError("backend boom"))
        vault._inflight["example.com"] = future
        assert await vault.load("example.com") is None

    def test_session_summary_is_expired(self) -> None:
        assert SessionSummary("a.com", 0.0, 1.0, 0, 0).is_expired is True
        assert SessionSummary("a.com", 0.0, None, 0, 0).is_expired is False

    def test_vault_metrics_derived(self) -> None:
        metrics = VaultMetrics(
            cache_hits=5,
            cache_misses=3,
            encryption_count=2,
            encryption_total_ms=10.0,
            decryption_count=4,
            decryption_total_ms=20.0,
        )
        assert metrics.cache_hit_rate == pytest.approx(0.625)
        assert metrics.avg_encryption_ms == 5.0
        assert metrics.avg_decryption_ms == 5.0
        empty = VaultMetrics()
        assert empty.cache_hit_rate == 0.0
        assert empty.avg_encryption_ms == 0.0
        assert empty.avg_decryption_ms == 0.0

    def test_estimate_entry_size_fallback(
        self, tmp_path: Path, vault_key: bytes
    ) -> None:
        vault = SessionVault(FileVaultBackend(tmp_path), vault_key)
        entry = SessionEntry("a.com", object(), 0.0, None)
        assert vault._estimate_entry_size(entry) == 2048

    async def test_cache_evict_one_evicts_oldest(
        self, tmp_path: Path, vault_key: bytes
    ) -> None:
        vault = SessionVault(FileVaultBackend(tmp_path), vault_key)
        await vault.save("a.com", {"cookies": [{"name": "x"}]})
        await vault.save("b.com", {"cookies": [{"name": "y"}]})
        vault._cache_evict_one()
        assert "a.com" not in vault._cache
        assert "b.com" in vault._cache
        assert vault._metrics.cache_evictions == 1

    async def test_list_summaries_empty(
        self, tmp_path: Path, vault_key: bytes
    ) -> None:
        vault = SessionVault(FileVaultBackend(tmp_path), vault_key)
        assert await vault.list_summaries() == []

    async def test_list_summaries_skips_missing_file(
        self, tmp_path: Path, vault_key: bytes
    ) -> None:
        backend = FileVaultBackend(tmp_path)
        vault = SessionVault(backend, vault_key)
        await vault.save("good.com", {"cookies": []})
        with patch.object(
            backend, "list_all", return_value=["good.com", "ghost.com"]
        ):
            summaries = await vault.list_summaries()
        assert [s.domain for s in summaries] == ["good.com"]

    async def test_cleanup_expired_with_domains(
        self, tmp_path: Path, vault_key: bytes
    ) -> None:
        backend = FileVaultBackend(tmp_path)
        vault = SessionVault(backend, vault_key)
        await vault.save("expired.com", {"cookies": []}, ttl_days=-1)
        await vault.save("alive.com", {"cookies": []})
        assert await vault.cleanup_expired() == 1
        assert "alive.com" in await backend.list_all()

    async def test_cleanup_expired_empty(
        self, tmp_path: Path, vault_key: bytes
    ) -> None:
        vault = SessionVault(FileVaultBackend(tmp_path), vault_key)
        assert await vault.cleanup_expired() == 0

    def test_cache_evict_one_empty_cache(
        self, tmp_path: Path, vault_key: bytes
    ) -> None:
        vault = SessionVault(FileVaultBackend(tmp_path), vault_key)
        vault._cache_evict_one()  # no-op on empty cache
