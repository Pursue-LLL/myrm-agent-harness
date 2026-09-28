"""Unit tests for EphemeralCredential and EphemeralCredentialStore with physical zeroization."""

from __future__ import annotations

import time

import pytest

from myrm_agent_harness.core.security.ephemeral_credentials import (
    EphemeralCredentialStore,
    validate_credential_key,
)


def test_validate_credential_key_success_and_blocked() -> None:
    assert validate_credential_key("db_password") == "DB_PASSWORD"
    assert validate_credential_key("API_TOKEN_123") == "API_TOKEN_123"

    with pytest.raises(ValueError, match="Blocked credential key"):
        validate_credential_key("PATH")

    with pytest.raises(ValueError, match="Blocked credential key"):
        validate_credential_key("LD_PRELOAD")

    with pytest.raises(ValueError, match="Invalid credential key"):
        validate_credential_key("123_INVALID")


def test_store_and_consume_single_use_zeroization() -> None:
    store = EphemeralCredentialStore()
    session_id = "test-session-1"

    cred = store.store_credential(
        session_id=session_id,
        key="MYSQL_PASSWORD",
        secret="SuperSecret123!",
        ttl_seconds=30.0,
        single_use=True,
    )

    handle_id = cred.handle_id
    assert handle_id.startswith("cred_ephemeral_")

    # Metadata peek does not expose secret
    summary = store.peek_summary(session_id, handle_id)
    assert summary is not None
    assert summary.key == "MYSQL_PASSWORD"
    assert not summary.is_consumed

    # First read succeeds
    val = store.consume_credential(session_id, handle_id)
    assert val == "SuperSecret123!"

    # Physical memory buffer must be wiped
    assert len(cred._material) == 0

    # Second read fails because single-use credential was consumed & zeroized
    with pytest.raises(KeyError):
        store.consume_credential(session_id, handle_id)


def test_session_isolation_and_purge() -> None:
    store = EphemeralCredentialStore()
    sess_a = "session-a"
    sess_b = "session-b"

    _ = store.store_credential(sess_a, "TOKEN_A", "secret-a")
    cred_b = store.store_credential(sess_b, "TOKEN_B", "secret-b")

    # A cannot consume B
    with pytest.raises(KeyError):
        store.consume_credential(sess_a, cred_b.handle_id)

    # Purge session A wipes A but leaves B
    purged = store.purge_session(sess_a)
    assert purged == 1
    assert store.list_summaries(sess_a) == []

    # B is still consumable
    assert store.consume_credential(sess_b, cred_b.handle_id) == "secret-b"


def test_ttl_expiration_and_cleanup() -> None:
    store = EphemeralCredentialStore()
    sess = "session-exp"

    cred = store.store_credential(sess, "TEMP_TOKEN", "temp-val", ttl_seconds=0.05)
    assert not cred.is_expired

    time.sleep(0.06)
    assert cred.is_expired

    with pytest.raises(ValueError, match="has expired"):
        store.consume_credential(sess, cred.handle_id)

    cleaned = store.cleanup_expired()
    assert cleaned == 1
    assert store.list_summaries(sess) == []
