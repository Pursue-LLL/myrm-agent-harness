"""Unit tests for ExternalSecretsManager, Single-Flight concurrency, and Sentinel integration."""

from __future__ import annotations

import concurrent.futures
import subprocess
import time
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.core.security.external_secrets import (
    ExternalSecretsManager,
    get_external_secrets_manager,
    resolve_external_secret,
)
from myrm_agent_harness.core.security.external_secrets.manager import _CacheEntry
from myrm_agent_harness.core.security.safe_exec import (
    credential_env_overrides,
)
from myrm_agent_harness.core.security.types import EphemeralUserCredential


@pytest.fixture(autouse=True)
def reset_manager_cache() -> None:
    get_external_secrets_manager().clear_cache()
    yield
    get_external_secrets_manager().clear_cache()


def test_manager_singleton() -> None:
    mgr1 = get_external_secrets_manager()
    mgr2 = get_external_secrets_manager()
    assert mgr1 is mgr2


@patch("subprocess.run")
def test_single_flight_concurrent_deduplication(mock_run: MagicMock) -> None:
    """Ensure concurrent callers requesting the same cold URI only trigger one CLI subprocess."""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "sk-single-flight-key\n"

    def _slow_run(*args: object, **kwargs: object) -> MagicMock:
        time.sleep(0.1)
        return mock_proc

    mock_run.side_effect = _slow_run

    ref = "op://Finance/Stripe/api_key"
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(resolve_external_secret, ref) for _ in range(5)]
        results = [f.result() for f in futures]

    assert all(r == "sk-single-flight-key" for r in results)
    assert mock_run.call_count == 1


@patch("subprocess.run")
def test_ttl_expiration(mock_run: MagicMock) -> None:
    """Ensure expired TTL triggers refetch."""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "sk-key-v1\n"
    mock_run.return_value = mock_proc

    manager = ExternalSecretsManager(default_ttl_seconds=0.05)
    ref = "op://Vault/Item/field"

    val1 = manager.resolve(ref)
    assert val1 == "sk-key-v1"
    assert mock_run.call_count == 1

    # Wait for TTL expiry
    time.sleep(0.08)

    mock_proc.stdout = "sk-key-v2\n"
    val2 = manager.resolve(ref)
    assert val2 == "sk-key-v2"
    assert mock_run.call_count == 2


@patch("subprocess.run")
def test_safe_exec_sentinel_voucher_wrapping(mock_run: MagicMock) -> None:
    """Ensure safe_exec wraps resolved external secrets into AES-256-GCM Sentinel vouchers."""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "sk-live-github-token-secret\n"
    mock_run.return_value = mock_proc

    creds = (
        EphemeralUserCredential(
            issuer="github",
            token="op://Engineering/GitHub/personal_access_token",
        ),
    )

    # When use_sentinel is False, returns plaintext
    env_plain = credential_env_overrides(creds, use_sentinel=False)
    assert env_plain["GITHUB_TOKEN"] == "sk-live-github-token-secret"

    # When use_sentinel is True, returns an opaque Sentinel voucher
    env_sentinel = credential_env_overrides(creds, use_sentinel=True)
    voucher = env_sentinel["GITHUB_TOKEN"]
    assert voucher.startswith("myrm-sent-v1.")
    assert voucher.endswith(".end")
    assert "sk-live-github" not in voucher


def test_invalidate_and_clear_cache() -> None:
    mgr = ExternalSecretsManager()
    mgr._cache["op://Vault/Item/f1"] = _CacheEntry(value="v1", expires_at=time.monotonic() + 100)
    mgr._cache["op://Vault/Item/f2"] = _CacheEntry(value="v2", expires_at=time.monotonic() + 100)

    mgr.invalidate("op://Vault/Item/f1")
    assert "op://Vault/Item/f1" not in mgr._cache
    assert "op://Vault/Item/f2" in mgr._cache

    mgr.clear_cache()
    assert len(mgr._cache) == 0


@patch("subprocess.run")
def test_probe_cli_health(mock_run: MagicMock) -> None:
    # 1. Op succeeds
    mock_run.return_value = MagicMock(returncode=0, stdout="2.8.0\n")
    health = get_external_secrets_manager().probe()
    assert health.available is True
    assert health.scheme == "op://"

    # 2. None succeed
    mock_run.side_effect = FileNotFoundError("CLI not installed")
    health_fail = get_external_secrets_manager().probe()
    assert health_fail.available is False
    assert "Neither 'op', 'bw', nor 'bws'" in (health_fail.error_message or "")


@patch("subprocess.run")
def test_single_flight_failure_propagation(mock_run: MagicMock) -> None:
    """Ensure that if the leader encounters an exception, followers receive that same exception."""
    from myrm_agent_harness.core.security.external_secrets import ExternalSecretResolutionError

    def _failing_run(*args: object, **kwargs: object) -> MagicMock:
        time.sleep(0.05)
        raise subprocess.SubprocessError("CLI crash")

    mock_run.side_effect = _failing_run

    manager = ExternalSecretsManager()
    ref = "op://Vault/Item/secret_err"

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(manager.resolve, ref) for _ in range(2)]
        for f in futures:
            with pytest.raises(ExternalSecretResolutionError):
                f.result()


@patch("subprocess.run")
def test_cli_error_cases(mock_run: MagicMock) -> None:
    from myrm_agent_harness.core.security.external_secrets import ExternalSecretResolutionError

    manager = ExternalSecretsManager()

    # 1. TimeoutExpired
    mock_run.side_effect = subprocess.TimeoutExpired(cmd="op", timeout=15.0)
    with pytest.raises(ExternalSecretResolutionError, match="timed out"):
        manager.resolve("op://Vault/Item/timeout")

    # 2. FileNotFoundError
    mock_run.side_effect = FileNotFoundError("Binary not found")
    with pytest.raises(ExternalSecretResolutionError, match="not installed or not found in system PATH"):
        manager.resolve("op://Vault/Item/not_found")

    # 3. Empty output
    mock_run.side_effect = None
    mock_run.return_value = MagicMock(returncode=0, stdout="   \n")
    with pytest.raises(ExternalSecretResolutionError, match="returned empty value"):
        manager.resolve("op://Vault/Item/empty")

    # 4. BWS invalid JSON
    mock_run.return_value = MagicMock(returncode=0, stdout="NOT_JSON")
    with pytest.raises(ExternalSecretResolutionError, match="Failed to parse bws JSON"):
        manager.resolve("bws://secret-uuid-invalid")


@patch("subprocess.run")
def test_cache_capacity_eviction(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="secret_val\n")
    manager = ExternalSecretsManager()

    # Pre-populate cache to max capacity
    for i in range(256):
        manager._cache[f"op://V/I/k{i}"] = _CacheEntry(
            value=f"val_{i}",
            expires_at=time.monotonic() + 100.0 + i,
        )

    assert len(manager._cache) == 256
    # Resolving new secret should evict oldest
    manager.resolve("op://V/I/new_secret")
    assert len(manager._cache) == 256
    assert "op://V/I/k0" not in manager._cache
    assert "op://V/I/new_secret" in manager._cache

