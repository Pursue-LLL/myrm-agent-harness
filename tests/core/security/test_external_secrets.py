"""Unit tests for ExternalSecretsManager, Single-Flight concurrency, and Sentinel integration."""

from __future__ import annotations

import concurrent.futures
import time
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.core.security.external_secrets import (
    ExternalSecretsManager,
    get_external_secrets_manager,
    resolve_external_secret,
)
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
