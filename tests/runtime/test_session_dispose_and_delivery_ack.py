"""Unit tests for SessionDisposePurger and DeliveryAckCoordinator.

Tests benchmarked against Paseo commit 92442e74 and Omnigent commit a9e76345:
1. Physical hard purge: all in-flight pending futures rejected with SessionDisposedError on teardown.
2. Prevention of new request dispatch on disposed session.
3. Normal single request resolution and explicit rejection.
4. Delivery ACK lifecycle: acknowledgement with RTT, timeout detection, and rejection.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from myrm_agent_harness.runtime.session_dispose import (
    DeliveryAckCoordinator,
    DeliveryAckStatus,
    SessionDisposedError,
    SessionDisposePurger,
    SessionLifecycleState,
)


@pytest.mark.asyncio
async def test_session_dispose_purges_all_pending_requests() -> None:
    """Test that all hanging in-flight futures are explicitly rejected upon session disposal."""
    purger = SessionDisposePurger(session_id="sess_paseo_test")
    assert purger.state == SessionLifecycleState.ACTIVE

    loop = asyncio.get_running_loop()
    f1 = purger.register_request("req_catalog", "fetchCatalog", loop=loop)
    f2 = purger.register_request("req_init", "initializeLsp", loop=loop)
    assert purger.pending_count == 2

    # Dispose the session (simulating workspace teardown or user abort)
    purged_count = purger.dispose(reason="Workspace teardown by user")
    assert purged_count == 2
    assert purger.state == SessionLifecycleState.DISPOSED
    assert purger.pending_count == 0

    # Both futures must immediately fail with SessionDisposedError rather than hanging forever
    with pytest.raises(SessionDisposedError) as exc_info1:
        await f1
    assert exc_info1.value.session_id == "sess_paseo_test"
    assert exc_info1.value.purged_request_count == 2
    assert "Workspace teardown by user" in exc_info1.value.reason

    with pytest.raises(SessionDisposedError) as exc_info2:
        await f2
    assert exc_info2.value.session_id == "sess_paseo_test"


@pytest.mark.asyncio
async def test_session_dispose_blocks_new_requests() -> None:
    """Test that registering requests on a disposed session immediately raises SessionDisposedError."""
    purger = SessionDisposePurger(session_id="sess_closed")
    purger.dispose(reason="Closed")

    loop = asyncio.get_running_loop()
    with pytest.raises(SessionDisposedError) as exc_info:
        purger.register_request("req_new", "someMethod", loop=loop)

    assert "Cannot dispatch request to an already disposed session" in exc_info.value.reason


@pytest.mark.asyncio
async def test_session_normal_resolve_and_reject() -> None:
    """Test standard lifecycle resolution and isolated rejection when session remains active."""
    purger = SessionDisposePurger(session_id="sess_active")
    loop = asyncio.get_running_loop()

    f_ok = purger.register_request("req_ok", "getData", loop=loop)
    f_err = purger.register_request("req_err", "getData", loop=loop)

    # 1. Resolve f_ok
    assert purger.resolve_request("req_ok", "payload_123") is True
    res = await f_ok
    assert res == "payload_123"

    # 2. Reject f_err
    assert purger.reject_request("req_err", ValueError("Bad input")) is True
    with pytest.raises(ValueError) as val_err:
        await f_err
    assert "Bad input" in str(val_err.value)

    assert purger.pending_count == 0


def test_delivery_ack_coordinator_lifecycle() -> None:
    """Test delivery acknowledgement confirmation, RTT measurement, and timeout auditing."""
    coordinator = DeliveryAckCoordinator(default_timeout_seconds=0.1)

    # Case 1: Successful delivery ACK with measured RTT
    coordinator.register_dispatch("msg_101", "agent_worker_a")
    time.sleep(0.01)  # small delta to measure RTT
    receipt_ack = coordinator.acknowledge_receipt("msg_101", "agent_worker_a")
    assert receipt_ack.status == DeliveryAckStatus.ACKNOWLEDGED
    assert receipt_ack.rtt_ms >= 5.0
    assert receipt_ack.message_id == "msg_101"

    card_ack = coordinator.render_ack_markdown_card(receipt_ack)
    assert "### 📨 跨智能体消息投递确认 (Delivery ACK) 卡片" in card_ack
    assert "ACKNOWLEDGED" in card_ack
    assert "> [!NOTE]" in card_ack

    # Case 2: Timeout detection
    coordinator.register_dispatch("msg_102", "agent_worker_b")
    # Immediate check should not be timed out
    assert coordinator.check_timeout("msg_102", "agent_worker_b") is None
    # Wait past timeout
    time.sleep(0.12)
    receipt_timeout = coordinator.check_timeout("msg_102", "agent_worker_b")
    assert receipt_timeout is not None
    assert receipt_timeout.status == DeliveryAckStatus.TIMED_OUT
    card_timeout = coordinator.render_ack_markdown_card(receipt_timeout)
    assert "> [!WARNING]" in card_timeout

    # Case 3: Explicit rejection
    coordinator.register_dispatch("msg_103", "agent_worker_c")
    receipt_reject = coordinator.reject_receipt("msg_103", "agent_worker_c", reason="Agent queue full")
    assert receipt_reject.status == DeliveryAckStatus.REJECTED
    card_reject = coordinator.render_ack_markdown_card(receipt_reject)
    assert "> [!CAUTION]" in card_reject
    assert "Agent queue full" in card_reject
