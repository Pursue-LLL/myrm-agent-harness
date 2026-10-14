"""cleanup_expired must set an unreadable session aside, never destroy it.

A saved login that cannot be decrypted is not known to be expired: a regenerated or rotated vault
key makes every file look that way. ``load`` already keeps such a file as ``.corrupted``; the
periodic sweep has to do the same, on a real file vault.
"""

from __future__ import annotations

import os
from pathlib import Path

import orjson
import pytest

from myrm_agent_harness.toolkits.browser.session_vault import SessionVault
from myrm_agent_harness.toolkits.browser.session_vault.backends import FileVaultBackend

_STATE = {"cookies": [{"name": "sid", "value": "secret", "domain": "example.com", "path": "/"}], "origins": []}


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    return tmp_path / "sessions"


@pytest.fixture
def backend(vault_dir: Path) -> FileVaultBackend:
    return FileVaultBackend(vault_dir)


def _corrupted(backend: FileVaultBackend, domain: str) -> Path:
    return backend._path(domain).with_suffix(".corrupted")


@pytest.mark.asyncio
async def test_rotated_key_keeps_every_session_as_corrupted_file(backend: FileVaultBackend) -> None:
    old_vault = SessionVault(backend, os.urandom(32))
    domains = ["a.example.com", "b.example.com", "c.example.com"]
    for domain in domains:
        await old_vault.save(domain, _STATE, ttl_days=30)
    originals = {domain: backend._path(domain).read_bytes() for domain in domains}

    new_vault = SessionVault(backend, os.urandom(32))
    removed = await new_vault.cleanup_expired()

    assert removed == len(domains)
    for domain in domains:
        assert not backend._path(domain).exists()
        assert _corrupted(backend, domain).read_bytes() == originals[domain]


@pytest.mark.asyncio
async def test_undecryptable_bytes_are_kept_as_corrupted_file(backend: FileVaultBackend) -> None:
    vault = SessionVault(backend, os.urandom(32))
    await backend.write("junk.example.com", b"not-a-valid-ciphertext-but-longer-than-29-bytes")

    assert await vault.cleanup_expired() == 1

    assert not backend._path("junk.example.com").exists()
    assert _corrupted(backend, "junk.example.com").read_bytes() == b"not-a-valid-ciphertext-but-longer-than-29-bytes"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [b"not json at all", orjson.dumps([1, 2, 3]), orjson.dumps({"expires_at": "tomorrow"})],
    ids=["not-json", "json-not-an-object", "non-numeric-expiry"],
)
async def test_decryptable_but_malformed_payload_is_kept_as_corrupted_file(
    backend: FileVaultBackend, payload: bytes
) -> None:
    vault = SessionVault(backend, os.urandom(32))
    ciphertext = vault._encrypt(payload)
    await backend.write("odd.example.com", ciphertext)

    assert await vault.cleanup_expired() == 1

    assert not backend._path("odd.example.com").exists()
    assert _corrupted(backend, "odd.example.com").read_bytes() == ciphertext


@pytest.mark.asyncio
async def test_expired_session_is_deleted_without_a_backup(backend: FileVaultBackend) -> None:
    vault = SessionVault(backend, os.urandom(32))
    await vault.save("old.example.com", _STATE, ttl_days=-1)

    assert await vault.cleanup_expired() == 1

    assert not backend._path("old.example.com").exists()
    assert not _corrupted(backend, "old.example.com").exists()


@pytest.mark.asyncio
async def test_live_sessions_and_sessions_without_expiry_are_untouched(backend: FileVaultBackend) -> None:
    vault = SessionVault(backend, os.urandom(32))
    await vault.save("live.example.com", _STATE, ttl_days=30)
    await vault.save("forever.example.com", _STATE, ttl_days=None)

    assert await vault.cleanup_expired() == 0

    for domain in ("live.example.com", "forever.example.com"):
        assert backend._path(domain).exists()
        assert not _corrupted(backend, domain).exists()
        loaded = await vault.load(domain)
        assert loaded is not None
        assert loaded.storage_state == _STATE


@pytest.mark.asyncio
async def test_a_cached_entry_does_not_outlive_its_set_aside_file(backend: FileVaultBackend) -> None:
    """The file becomes unreadable behind the vault's back; the sweep must drop the stale cache too."""
    key = os.urandom(32)
    vault = SessionVault(backend, key)
    await vault.save("cached.example.com", _STATE, ttl_days=30)
    assert await vault.load("cached.example.com") is not None
    backend._path("cached.example.com").write_bytes(b"x" * 64)

    assert await vault.cleanup_expired() == 1

    assert await vault.load("cached.example.com") is None
