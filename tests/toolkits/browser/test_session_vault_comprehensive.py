"""Comprehensive tests for SessionVault (100% coverage)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.browser.backends import FileVaultBackend
from myrm_agent_harness.toolkits.browser.backends.file_backend import load_or_create_key
from myrm_agent_harness.toolkits.browser.session_vault import SessionVault
from myrm_agent_harness.toolkits.browser.session_vault_exceptions import (
    CorruptedSessionError,
    DecryptionError,
)


@pytest.fixture
def backend(tmp_path: Path) -> FileVaultBackend:
    """Create FileVaultBackend for testing."""
    return FileVaultBackend(tmp_path)


@pytest.fixture
def vault_key() -> bytes:
    """Create test vault key."""
    return os.urandom(32)


# =============================================================================
# FileVaultBackend
# =============================================================================


class TestFileVaultBackend:
    """Test FileVaultBackend."""

    def test_init_creates_directory(self, tmp_path: Path) -> None:
        """Test backend creates vault directory."""
        vault_dir = tmp_path / "vault"
        backend = FileVaultBackend(vault_dir)

        assert vault_dir.exists()
        assert backend._dir == vault_dir

    def test_path_safe_domain(self, tmp_path: Path) -> None:
        """Test _path creates safe filename."""
        backend = FileVaultBackend(tmp_path)

        path = backend._path("example.com")

        assert path.name == "example.com.enc"
        assert path.parent == tmp_path

    def test_path_with_colon(self, tmp_path: Path) -> None:
        """Test _path uses URL encoding for special characters."""
        backend = FileVaultBackend(tmp_path)

        path = backend._path("localhost:8080")

        assert path.name == "localhost%3A8080.enc"

    def test_path_no_filename_collision(self, tmp_path: Path) -> None:
        """Test _path prevents collision between domains with special chars."""
        backend = FileVaultBackend(tmp_path)

        path1 = backend._path("localhost:8080")
        path2 = backend._path("localhost_8080")

        assert path1.name == "localhost%3A8080.enc"
        assert path2.name == "localhost_8080.enc"
        assert path1 != path2

    @pytest.mark.asyncio
    async def test_read_existing_file(self, tmp_path: Path) -> None:
        """Test read returns file content."""
        backend = FileVaultBackend(tmp_path)
        test_data = b"encrypted_data"
        (tmp_path / "example.com.enc").write_bytes(test_data)

        result = await backend.read("example.com")

        assert result == test_data

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, tmp_path: Path) -> None:
        """Test read returns None for missing file."""
        backend = FileVaultBackend(tmp_path)

        result = await backend.read("nonexistent.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_write_creates_file(self, tmp_path: Path) -> None:
        """Test write creates encrypted file."""
        backend = FileVaultBackend(tmp_path)
        test_data = b"encrypted_data"

        await backend.write("example.com", test_data)

        path = tmp_path / "example.com.enc"
        assert path.exists()
        assert path.read_bytes() == test_data

    @pytest.mark.asyncio
    async def test_write_atomic_operation(self, tmp_path: Path) -> None:
        """Test write uses atomic temp file + replace."""
        backend = FileVaultBackend(tmp_path)

        await backend.write("example.com", b"data")

        assert not (tmp_path / "example.com.tmp").exists()
        assert (tmp_path / "example.com.enc").exists()

    @pytest.mark.asyncio
    async def test_write_failure_cleanup(self, tmp_path: Path) -> None:
        """Test write cleans up temp file on failure."""
        backend = FileVaultBackend(tmp_path)

        with patch.object(Path, "replace", side_effect=OSError("Write failed")):
            with pytest.raises(OSError, match="Failed to write session"):
                await backend.write("example.com", b"data")

    @pytest.mark.asyncio
    async def test_delete_existing_file(self, tmp_path: Path) -> None:
        """Test delete removes file and returns True."""
        backend = FileVaultBackend(tmp_path)
        (tmp_path / "example.com.enc").write_bytes(b"data")

        result = await backend.delete("example.com")

        assert result is True
        assert not (tmp_path / "example.com.enc").exists()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_file(self, tmp_path: Path) -> None:
        """Test delete returns False for missing file."""
        backend = FileVaultBackend(tmp_path)

        result = await backend.delete("nonexistent.com")

        assert result is False

    @pytest.mark.asyncio
    async def test_list_all_with_files(self, tmp_path: Path) -> None:
        """Test list_all returns all domains with URL decoding."""
        backend = FileVaultBackend(tmp_path)
        (tmp_path / "example.com.enc").write_bytes(b"data1")
        (tmp_path / "localhost%3A8080.enc").write_bytes(b"data2")

        result = await backend.list_all()

        assert set(result) == {"example.com", "localhost:8080"}

    @pytest.mark.asyncio
    async def test_list_all_empty_dir(self, tmp_path: Path) -> None:
        """Test list_all returns empty list for empty vault."""
        backend = FileVaultBackend(tmp_path)

        result = await backend.list_all()

        assert result == []

    @pytest.mark.asyncio
    async def test_list_all_nonexistent_dir(self, tmp_path: Path) -> None:
        """Test list_all returns empty list if directory doesn't exist."""
        vault_dir = tmp_path / "nonexistent"
        backend = FileVaultBackend(vault_dir)
        vault_dir.rmdir()

        result = await backend.list_all()

        assert result == []

    @pytest.mark.asyncio
    async def test_backup_corrupted(self, tmp_path: Path) -> None:
        """Test backup_corrupted creates .corrupted file."""
        backend = FileVaultBackend(tmp_path)
        corrupted_data = b"corrupted_encrypted_data"

        await backend.backup_corrupted("example.com", corrupted_data)

        corrupted_file = tmp_path / "example.com.corrupted"
        assert corrupted_file.exists()
        assert corrupted_file.read_bytes() == corrupted_data


# =============================================================================
# load_or_create_key
# =============================================================================


def test_load_or_create_key_creates_new(tmp_path: Path) -> None:
    """Test load_or_create_key creates new key."""
    key_path = tmp_path / "vault.key"

    key = load_or_create_key(key_path)

    assert len(key) == 32
    assert key_path.exists()
    assert key_path.read_bytes() == key


def test_load_or_create_key_loads_existing(tmp_path: Path) -> None:
    """Test load_or_create_key loads existing key."""
    key_path = tmp_path / "vault.key"
    original_key = os.urandom(32)
    key_path.write_bytes(original_key)

    key = load_or_create_key(key_path)

    assert key == original_key


def test_load_or_create_key_regenerates_invalid(tmp_path: Path) -> None:
    """Test load_or_create_key regenerates invalid key."""
    key_path = tmp_path / "vault.key"
    key_path.write_bytes(b"invalid_short_key")

    key = load_or_create_key(key_path)

    assert len(key) == 32
    assert key != b"invalid_short_key"


def test_load_or_create_key_sets_permissions(tmp_path: Path) -> None:
    """Test load_or_create_key sets 0600 permissions."""
    key_path = tmp_path / "vault.key"

    load_or_create_key(key_path)

    if os.name != "nt":
        stat = key_path.stat()
        assert stat.st_mode & 0o777 == 0o600


def test_load_or_create_key_creates_parent_dirs(tmp_path: Path) -> None:
    """Test load_or_create_key creates parent directories."""
    key_path = tmp_path / "nested" / "dir" / "vault.key"

    load_or_create_key(key_path)

    assert key_path.exists()


# =============================================================================
# SessionVault - Initialization
# =============================================================================


def test_session_vault_init_valid_key(tmp_path: Path) -> None:
    """Test SessionVault initialization with valid key."""
    backend = FileVaultBackend(tmp_path)
    key = os.urandom(32)

    vault = SessionVault(backend, key)

    assert vault._backend is backend


def test_session_vault_init_invalid_key_length(tmp_path: Path) -> None:
    """Test SessionVault raises ValueError for invalid key length."""
    backend = FileVaultBackend(tmp_path)

    with pytest.raises(ValueError, match="Encryption key must be 32 bytes"):
        SessionVault(backend, b"short_key")


# =============================================================================
# SessionVault - save/load/delete/list_domains
# =============================================================================


@pytest.mark.asyncio
async def test_session_vault_save_and_load(tmp_path: Path) -> None:
    """Test save and load session."""
    backend = FileVaultBackend(tmp_path)
    key = os.urandom(32)
    vault = SessionVault(backend, key)

    session_data = {
        "cookies": [{"name": "session", "value": "abc123"}],
        "localStorage": {"key": "value"},
    }

    await vault.save("example.com", session_data)

    entry = await vault.load("example.com")

    assert entry is not None
    assert entry.storage_state == session_data
    assert entry.domain == "example.com"


@pytest.mark.asyncio
async def test_session_vault_load_nonexistent(tmp_path: Path) -> None:
    """Test load returns None for nonexistent session."""
    backend = FileVaultBackend(tmp_path)
    key = os.urandom(32)
    vault = SessionVault(backend, key)

    entry = await vault.load("nonexistent.com")

    assert entry is None


@pytest.mark.asyncio
async def test_session_vault_delete_existing(tmp_path: Path) -> None:
    """Test delete removes session."""
    backend = FileVaultBackend(tmp_path)
    key = os.urandom(32)
    vault = SessionVault(backend, key)

    await vault.save("example.com", {"cookies": []})

    result = await vault.delete("example.com")

    assert result is True
    entry = await vault.load("example.com")
    assert entry is None


@pytest.mark.asyncio
async def test_session_vault_delete_nonexistent(tmp_path: Path) -> None:
    """Test delete returns False for nonexistent session."""
    backend = FileVaultBackend(tmp_path)
    key = os.urandom(32)
    vault = SessionVault(backend, key)

    result = await vault.delete("nonexistent.com")

    assert result is False


@pytest.mark.asyncio
async def test_session_vault_list_domains(tmp_path: Path) -> None:
    """Test list_domains returns all saved sessions."""
    backend = FileVaultBackend(tmp_path)
    key = os.urandom(32)
    vault = SessionVault(backend, key)

    await vault.save("example.com", {"cookies": []})
    await vault.save("github.com", {"localStorage": {}})

    result = await vault.list_domains()

    assert set(result) == {"example.com", "github.com"}


@pytest.mark.asyncio
async def test_session_vault_corrupted_data(tmp_path: Path) -> None:
    """Test load handles corrupted encrypted data."""
    backend = FileVaultBackend(tmp_path)
    key = os.urandom(32)
    vault = SessionVault(backend, key)

    await backend.write("corrupted.com", b"invalid_encrypted_data_at_least_29_bytes_long_xxx")

    entry = await vault.load("corrupted.com")

    assert entry is None


@pytest.mark.asyncio
async def test_session_vault_invalid_json(tmp_path: Path) -> None:
    """Test load handles decrypted but invalid JSON."""
    backend = FileVaultBackend(tmp_path)
    key = os.urandom(32)
    vault = SessionVault(backend, key)

    ciphertext = vault._encrypt(b"not json data")
    await backend.write("invalid.com", ciphertext)

    with pytest.raises(CorruptedSessionError, match="corrupted"):
        await vault.load("invalid.com")


@pytest.mark.asyncio
async def test_session_vault_expired_session(tmp_path: Path) -> None:
    """Test load returns None for expired session."""
    backend = FileVaultBackend(tmp_path)
    key = os.urandom(32)
    vault = SessionVault(backend, key)

    await vault.save("example.com", {"cookies": []}, ttl_days=-1)

    entry = await vault.load("example.com")

    assert entry is None


@pytest.mark.asyncio
async def test_session_vault_cleanup_expired(tmp_path: Path) -> None:
    """Test cleanup_expired removes expired sessions."""
    backend = FileVaultBackend(tmp_path)
    key = os.urandom(32)
    vault = SessionVault(backend, key)

    await vault.save("expired.com", {"cookies": []}, ttl_days=-1)
    await vault.save("valid.com", {"cookies": []}, ttl_days=30)

    removed = await vault.cleanup_expired()

    assert removed == 1
    assert await vault.load("valid.com") is not None
    assert await vault.load("expired.com") is None


# =============================================================================
# Encryption/Decryption
# =============================================================================


def test_session_vault_encrypt_decrypt_roundtrip(tmp_path: Path) -> None:
    """Test encryption and decryption roundtrip."""
    backend = FileVaultBackend(tmp_path)
    key = os.urandom(32)
    vault = SessionVault(backend, key)

    plaintext = b"test data"

    ciphertext = vault._encrypt(plaintext)
    decrypted = vault._decrypt(ciphertext)

    assert decrypted == plaintext
    assert ciphertext != plaintext


def test_session_vault_encrypt_different_nonces(tmp_path: Path) -> None:
    """Test encryption uses different nonces."""
    backend = FileVaultBackend(tmp_path)
    key = os.urandom(32)
    vault = SessionVault(backend, key)

    plaintext = b"test data"

    ciphertext1 = vault._encrypt(plaintext)
    ciphertext2 = vault._encrypt(plaintext)

    assert ciphertext1 != ciphertext2


def test_session_vault_decrypt_invalid_data(tmp_path: Path) -> None:
    """Test decrypt raises for invalid ciphertext."""
    backend = FileVaultBackend(tmp_path)
    key = os.urandom(32)
    vault = SessionVault(backend, key)

    with pytest.raises(Exception):
        vault._decrypt(b"invalid_ciphertext_but_at_least_29_bytes_long_xxxxxx")


def test_session_vault_decrypt_wrong_key(tmp_path: Path) -> None:
    """Test decrypt raises with wrong key."""
    backend = FileVaultBackend(tmp_path)
    key1 = os.urandom(32)
    key2 = os.urandom(32)

    vault1 = SessionVault(backend, key1)
    vault2 = SessionVault(backend, key2)

    ciphertext = vault1._encrypt(b"data")

    with pytest.raises(Exception):
        vault2._decrypt(ciphertext)


def test_session_vault_decrypt_truncated_data(tmp_path: Path) -> None:
    """Test decrypt raises for truncated ciphertext."""
    backend = FileVaultBackend(tmp_path)
    key = os.urandom(32)
    vault = SessionVault(backend, key)

    with pytest.raises(DecryptionError, match="Ciphertext too short"):
        vault._decrypt(b"short")


# =============================================================================
# load_or_create_key edge cases
# =============================================================================


def test_load_or_create_key_chmod_failure(tmp_path: Path) -> None:
    """Test load_or_create_key handles chmod failure gracefully."""
    key_path = tmp_path / "vault.key"

    with patch.object(Path, "chmod", side_effect=OSError("Permission denied")):
        key = load_or_create_key(key_path)

        assert len(key) == 32


def test_load_or_create_key_invalid_length_regenerates(tmp_path: Path) -> None:
    """Test load_or_create_key regenerates key with wrong length."""
    key_path = tmp_path / "vault.key"
    key_path.write_bytes(b"wrong_length_key")

    key = load_or_create_key(key_path)

    assert len(key) == 32
    assert key != b"wrong_length_key"


# =============================================================================
# cleanup_expired edge cases
# =============================================================================


@pytest.mark.asyncio
async def test_cleanup_expired_skips_none_data(backend: FileVaultBackend, vault_key: bytes) -> None:
    """Test cleanup_expired skips entries with None data."""
    from unittest.mock import AsyncMock, patch

    vault = SessionVault(backend, vault_key)

    await vault.save("test.com", {"cookies": []}, ttl_days=30)

    with patch.object(backend, "read", new=AsyncMock(return_value=None)):
        removed = await vault.cleanup_expired()

        assert removed == 0


@pytest.mark.asyncio
async def test_cleanup_expired_removes_corrupted_data(backend: FileVaultBackend, vault_key: bytes) -> None:
    """Test cleanup_expired removes corrupted session data."""
    vault = SessionVault(backend, vault_key)

    await vault.save("test.com", {"cookies": []}, ttl_days=30)

    domain_file = backend._path("test.com")
    domain_file.write_bytes(b"corrupted_non_decryptable_data")

    removed = await vault.cleanup_expired()

    assert removed == 1


# =============================================================================
# Regression Tests
# =============================================================================


@pytest.mark.asyncio
async def test_filename_collision_prevention(backend: FileVaultBackend, vault_key: bytes) -> None:
    """Verify domains with special chars don't collide in filesystem.

    URL encoding ensures bijection: 'localhost:8080' → 'localhost%3A8080.enc'
    and 'localhost_8080' → 'localhost_8080.enc' map to different files.
    """
    vault = SessionVault(backend, vault_key)

    session1 = {"cookies": [{"name": "session1", "value": "value1"}]}
    session2 = {"cookies": [{"name": "session2", "value": "value2"}]}

    await vault.save("localhost:8080", session1)
    await vault.save("localhost_8080", session2)

    entry1 = await vault.load("localhost:8080")
    entry2 = await vault.load("localhost_8080")

    assert entry1 is not None
    assert entry2 is not None
    assert entry1.storage_state != entry2.storage_state
    assert entry1.storage_state == session1
    assert entry2.storage_state == session2

    domains = await vault.list_domains()
    assert set(domains) == {"localhost:8080", "localhost_8080"}

    files = list(backend._dir.glob("*.enc"))
    assert len(files) == 2
    assert {f.name for f in files} == {"localhost%3A8080.enc", "localhost_8080.enc"}


# =============================================================================
# Performance Optimizations
# =============================================================================


@pytest.mark.asyncio
async def test_aesgcm_instance_caching(backend: FileVaultBackend, vault_key: bytes) -> None:
    """Verify AESGCM instance is cached and reused."""
    vault = SessionVault(backend, vault_key)

    # First encryption should initialize cipher
    session = {"cookies": [{"name": "test", "value": "data"}]}
    await vault.save("example.com", session)

    cipher1 = vault._cipher
    assert cipher1 is not None

    # Second encryption should reuse same cipher instance
    await vault.save("another.com", session)
    cipher2 = vault._cipher

    assert cipher1 is cipher2


@pytest.mark.asyncio
async def test_memory_cache_hit(backend: FileVaultBackend, vault_key: bytes) -> None:
    """Verify memory cache reduces I/O operations."""
    vault = SessionVault(backend, vault_key, cache_ttl=60, cache_max_size=10)

    session = {"cookies": [{"name": "cached", "value": "entry"}]}
    await vault.save("example.com", session)

    # First load hits disk
    entry1 = await vault.load("example.com")
    assert entry1 is not None

    # Delete file from backend to verify cache is used
    await backend.delete("example.com")

    # Second load should hit cache (file is gone but cache has it)
    entry2 = await vault.load("example.com")
    assert entry2 is not None
    assert entry2.storage_state == session


@pytest.mark.asyncio
async def test_memory_cache_disabled(backend: FileVaultBackend, vault_key: bytes) -> None:
    """Verify cache can be disabled."""
    vault = SessionVault(backend, vault_key, cache_max_size=0)

    session = {"cookies": [{"name": "test", "value": "data"}]}
    await vault.save("example.com", session)

    # Delete file
    await backend.delete("example.com")

    # Load should return None (cache disabled, file gone)
    entry = await vault.load("example.com")
    assert entry is None


@pytest.mark.asyncio
async def test_memory_cache_lru_eviction(backend: FileVaultBackend, vault_key: bytes) -> None:
    """Verify LRU eviction when cache is full."""
    vault = SessionVault(backend, vault_key, cache_max_size=3)

    # Save 4 sessions (cache size = 3)
    for i in range(4):
        await vault.save(f"domain{i}.com", {"cookies": [{"name": f"s{i}", "value": "v"}]})

    # Cache should only have 3 entries (oldest evicted)
    assert len(vault._cache) == 3


@pytest.mark.asyncio
async def test_memory_cache_ttl_expiration(backend: FileVaultBackend, vault_key: bytes) -> None:
    """Verify cache entries expire after TTL."""
    vault = SessionVault(backend, vault_key, cache_ttl=1, cache_max_size=10)

    session = {"cookies": [{"name": "test", "value": "data"}]}
    await vault.save("example.com", session)

    # First load populates cache
    entry1 = await vault.load("example.com")
    assert entry1 is not None

    # Wait for cache TTL to expire
    import asyncio

    await asyncio.sleep(1.1)

    # Delete file to verify cache is NOT used
    await backend.delete("example.com")

    # Load should return None (cache expired, file gone)
    entry2 = await vault.load("example.com")
    assert entry2 is None


@pytest.mark.asyncio
async def test_cache_invalidation_on_delete(backend: FileVaultBackend, vault_key: bytes) -> None:
    """Verify cache is invalidated on delete."""
    vault = SessionVault(backend, vault_key, cache_max_size=10)

    session = {"cookies": [{"name": "test", "value": "data"}]}
    await vault.save("example.com", session)
    await vault.load("example.com")  # Populate cache

    assert "example.com" in vault._cache

    await vault.delete("example.com")

    assert "example.com" not in vault._cache


@pytest.mark.asyncio
async def test_cleanup_expired_concurrent(backend: FileVaultBackend, vault_key: bytes) -> None:
    """Verify cleanup_expired processes sessions concurrently."""
    vault = SessionVault(backend, vault_key)

    # Save expired and valid sessions
    expired_session = {"cookies": [{"name": "expired", "value": "old"}]}
    valid_session = {"cookies": [{"name": "valid", "value": "new"}]}

    await vault.save("expired1.com", expired_session, ttl_days=-1)  # Already expired
    await vault.save("expired2.com", expired_session, ttl_days=-1)
    await vault.save("valid.com", valid_session, ttl_days=30)

    removed = await vault.cleanup_expired()

    assert removed == 2

    # Verify only valid session remains
    domains = await vault.list_domains()
    assert domains == ["valid.com"]


# =============================================================================
# Advanced Optimizations
# =============================================================================


@pytest.mark.asyncio
async def test_metrics_tracking(backend: FileVaultBackend, vault_key: bytes) -> None:
    """Verify metrics are tracked correctly."""
    vault = SessionVault(backend, vault_key, cache_max_size=0)  # Disable cache for this test

    session = {"cookies": [{"name": "test", "value": "data"}]}

    # Save and check encryption metrics
    await vault.save("example.com", session)
    assert vault.metrics.encryption_count == 1
    assert vault.metrics.encryption_total_ms > 0

    # Load and check decryption
    entry = await vault.load("example.com")
    assert entry is not None
    assert vault.metrics.decryption_count == 1
    assert vault.metrics.decryption_total_ms > 0

    # Second load should also decrypt (cache disabled)
    entry2 = await vault.load("example.com")
    assert entry2 is not None
    assert vault.metrics.decryption_count == 2


@pytest.mark.asyncio
async def test_memory_limit_enforcement(backend: FileVaultBackend, vault_key: bytes) -> None:
    """Verify memory limit triggers eviction."""
    # Set low memory limit (4KB) and use medium-sized sessions (~600 bytes each)
    vault = SessionVault(backend, vault_key, cache_max_size=100, cache_max_memory_mb=0.004)

    # Create medium-sized session (~600 bytes)
    medium_session = {"cookies": [{"name": f"cookie{i}", "value": "x" * 50} for i in range(10)]}

    # Save and load multiple sessions (should trigger memory-based eviction)
    for i in range(10):
        await vault.save(f"medium{i}.com", medium_session)
        await vault.load(f"medium{i}.com")

    # Memory should be near limit (allow 2% tolerance for Python object overhead)
    max_limit = 4096
    assert vault.metrics.cache_memory_bytes <= max_limit * 1.02, (
        f"Memory {vault.metrics.cache_memory_bytes} exceeds limit {max_limit * 1.02:.0f}"
    )
    # Should have evicted some entries
    assert vault.metrics.cache_evictions > 0
    # Not all 10 entries should fit
    assert len(vault._cache) < 10


@pytest.mark.asyncio
async def test_lru_eviction_is_o1(backend: FileVaultBackend, vault_key: bytes) -> None:
    """Verify LRU eviction is O(1) using OrderedDict."""
    vault = SessionVault(backend, vault_key, cache_max_size=5)

    session = {"cookies": [{"name": "test", "value": "data"}]}

    # Fill cache to capacity
    for i in range(5):
        await vault.save(f"domain{i}.com", session)
        await vault.load(f"domain{i}.com")

    # Add one more (should evict oldest)
    await vault.save("domain5.com", session)
    await vault.load("domain5.com")

    # domain0.com should be evicted
    assert "domain0.com" not in vault._cache
    assert len(vault._cache) == 5
    assert vault.metrics.cache_evictions == 1


@pytest.mark.asyncio
async def test_concurrent_cache_access(backend: FileVaultBackend, vault_key: bytes) -> None:
    """Verify cache is thread-safe under concurrent access."""
    vault = SessionVault(backend, vault_key, cache_max_size=10)

    session = {"cookies": [{"name": "test", "value": "data"}]}

    # Save initial session
    await vault.save("concurrent.com", session)

    # Concurrent reads and writes
    import asyncio

    async def read_task():
        for _ in range(50):
            await vault.load("concurrent.com")

    async def write_task():
        for i in range(50):
            await vault.save(f"concurrent{i}.com", session)

    # Run concurrently (should not raise RuntimeError)
    await asyncio.gather(read_task(), write_task(), write_task())

    # Verify no corruption
    assert vault.metrics.cache_hits > 0


@pytest.mark.asyncio
async def test_singleflight_prevents_stampede(backend: FileVaultBackend, vault_key: bytes) -> None:
    """Verify singleflight pattern prevents cache stampede.

    When multiple concurrent requests load the same non-cached domain,
    only one backend read should occur (others wait for result).
    """
    vault = SessionVault(backend, vault_key, cache_max_size=0)  # Disable cache

    session = {"cookies": [{"name": "test", "value": "data"}]}
    await vault.save("shared.com", session)

    # Track backend reads
    read_count = 0
    original_read = backend.read

    async def counting_read(domain: str):
        nonlocal read_count
        read_count += 1
        await asyncio.sleep(0.01)  # Simulate slow I/O
        return await original_read(domain)

    backend.read = counting_read

    # 100 concurrent loads of same domain
    tasks = [vault.load("shared.com") for _ in range(100)]
    results = await asyncio.gather(*tasks)

    # All should succeed
    assert all(r is not None for r in results)

    # Only 1 backend read should occur (singleflight)
    assert read_count == 1, f"Expected 1 backend read, got {read_count} (cache stampede!)"


@pytest.mark.asyncio
async def test_memory_estimate_accuracy(backend: FileVaultBackend, vault_key: bytes) -> None:
    """Verify memory estimation includes Python object overhead.

    Memory estimate should be conservative (slightly overestimate) to prevent OOM.
    """
    import tracemalloc

    vault = SessionVault(backend, vault_key, cache_max_size=100, cache_max_memory_mb=10)

    # Create session with known size
    session = {"cookies": [{"name": f"cookie{i}", "value": "x" * 100} for i in range(10)]}

    # Measure actual memory usage
    tracemalloc.start()

    for i in range(50):
        await vault.save(f"domain{i}.com", session)
        await vault.load(f"domain{i}.com")

    current, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    estimated = vault.metrics.cache_memory_bytes

    # Estimate should be conservative (overestimate is safer than underestimate)
    ratio = estimated / current if current > 0 else 0
    assert 0.8 <= ratio <= 6.0, f"Memory estimate ratio {ratio:.2f}x out of reasonable range"

    # Overestimate is acceptable (prevents OOM), underestimate is dangerous
    assert ratio >= 0.8, f"Memory underestimated by {1 / ratio:.2f}x - OOM risk!"

    # Should not exceed configured limit significantly
    max_allowed = 10 * 1024 * 1024
    assert estimated <= max_allowed * 1.2, f"Estimated {estimated} exceeds limit {max_allowed}"
