"""Tests for CancellationRegistry."""

import time

import pytest

from myrm_agent_harness.utils.runtime.cancellation import (
    CancellationRegistry,
    CancellationToken,
    CancelReason,
)


@pytest.fixture(autouse=True)
def cleanup_registry():
    """Clean up registry before and after each test."""
    CancellationRegistry._tokens.clear()
    yield
    CancellationRegistry._tokens.clear()


def test_register_and_unregister():
    """Test basic register and unregister operations."""
    token = CancellationToken(request_id="test-request-1")
    CancellationRegistry.register(token)

    assert CancellationRegistry.get_active_count() == 1

    CancellationRegistry.unregister("test-request-1")
    assert CancellationRegistry.get_active_count() == 0


def test_cancel_by_request_id():
    """Test cancelling a request by ID."""
    token = CancellationToken(request_id="test-request-2")
    CancellationRegistry.register(token)

    assert not token.is_cancelled

    success = CancellationRegistry.cancel("test-request-2", CancelReason.USER_CANCELLED)
    assert success
    assert token.is_cancelled
    assert token.cancel_reason == CancelReason.USER_CANCELLED


def test_cancel_nonexistent_request():
    """Test cancelling a non-existent request returns False."""
    success = CancellationRegistry.cancel("nonexistent", CancelReason.USER_CANCELLED)
    assert not success


def test_cancel_already_cancelled():
    """Test cancelling an already-cancelled request returns False."""
    token = CancellationToken(request_id="test-request-3")
    CancellationRegistry.register(token)

    token.cancel(CancelReason.DISCONNECT)
    success = CancellationRegistry.cancel("test-request-3", CancelReason.USER_CANCELLED)
    assert not success


def test_ttl_cleanup():
    """Test TTL-based cleanup of expired tokens."""
    old_token = CancellationToken(request_id="old-request")
    old_token._created_at = time.time() - 3700  # 1 hour + 100 seconds ago

    new_token = CancellationToken(request_id="new-request")

    CancellationRegistry.register(old_token)
    CancellationRegistry.register(new_token)

    assert CancellationRegistry.get_active_count() == 2

    cleaned = CancellationRegistry.cleanup_expired(ttl_seconds=3600)
    assert cleaned == 1
    assert CancellationRegistry.get_active_count() == 1


def test_multiple_tokens():
    """Test handling multiple tokens concurrently."""
    tokens = [CancellationToken(request_id=f"request-{i}") for i in range(5)]
    for token in tokens:
        CancellationRegistry.register(token)

    assert CancellationRegistry.get_active_count() == 5

    CancellationRegistry.cancel("request-2", CancelReason.TIMEOUT)
    assert tokens[2].is_cancelled
    assert not tokens[0].is_cancelled
    assert not tokens[4].is_cancelled


def test_cancel_with_custom_reason():
    """Test cancelling with a custom string reason."""
    token = CancellationToken(request_id="test-request-4")
    CancellationRegistry.register(token)

    CancellationRegistry.cancel("test-request-4", "Custom cancellation reason")
    assert token.is_cancelled
    assert token.cancel_reason == "Custom cancellation reason"
