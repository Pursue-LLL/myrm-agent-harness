"""Tests for DeadLetterQueue permanent-failure callback."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from myrm_agent_harness.infra.delivery.dead_letter import DeadLetterQueue
from myrm_agent_harness.infra.delivery.storage import QueuedDelivery, move_to_failed


@pytest.mark.asyncio
async def test_dlq_invokes_on_permanent_failure_when_max_retries_exceeded(tmp_path) -> None:
    dlq_dir = tmp_path / "dlq"
    dlq_dir.mkdir()
    callback = AsyncMock()
    enqueue_mock = AsyncMock()

    dlq = DeadLetterQueue(
        enqueue_fn=enqueue_mock,
        base_dir=dlq_dir,
        max_retries=2,
        on_permanent_failure=callback,
    )

    exhausted = QueuedDelivery(
        id="exhausted_msg",
        channel="telegram",
        recipient="user1",
        content={"content": "hello"},
        enqueued_at=time.time(),
        priority=2,
        retry_count=2,
        last_attempt_at=time.time(),
        last_error="send failed",
        failed_at=time.time(),
    )
    await move_to_failed(exhausted, base_dir=dlq_dir)

    await dlq._process_failed_messages()
    await dlq._process_failed_messages()

    callback.assert_awaited_once()
    assert callback.await_args.args[0].id == "exhausted_msg"
    assert callback.await_args.args[1] == "send failed"
    enqueue_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_dlq_skips_duplicate_permanent_failure_after_sync_notify(tmp_path) -> None:
    """Sync path notifies immediately; DLQ loop must not fire callback again."""
    dlq_dir = tmp_path / "dlq"
    dlq_dir.mkdir()
    callback = AsyncMock()
    enqueue_mock = AsyncMock()

    dlq = DeadLetterQueue(
        enqueue_fn=enqueue_mock,
        base_dir=dlq_dir,
        max_retries=2,
        on_permanent_failure=callback,
    )

    exhausted = QueuedDelivery(
        id="already_notified",
        channel="telegram",
        recipient="user1",
        content={"content": "hello"},
        enqueued_at=time.time(),
        priority=2,
        retry_count=2,
        last_attempt_at=time.time(),
        last_error="send failed",
        failed_at=time.time(),
    )
    await move_to_failed(exhausted, base_dir=dlq_dir)
    dlq.mark_permanent_failure_notified("already_notified")

    await dlq._process_failed_messages()

    callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_dlq_on_permanent_failure_callback_exception_is_logged(tmp_path) -> None:
    dlq_dir = tmp_path / "dlq"
    dlq_dir.mkdir()

    async def failing_callback(_delivery: QueuedDelivery, _reason: str) -> None:
        raise RuntimeError("callback failed")

    dlq = DeadLetterQueue(
        enqueue_fn=AsyncMock(),
        base_dir=dlq_dir,
        max_retries=1,
        on_permanent_failure=failing_callback,
    )

    exhausted = QueuedDelivery(
        id="cb_fail_msg",
        channel="telegram",
        recipient="user1",
        content={"content": "hello"},
        enqueued_at=time.time(),
        priority=2,
        retry_count=1,
        last_attempt_at=time.time(),
        last_error="send failed",
        failed_at=time.time(),
    )
    await move_to_failed(exhausted, base_dir=dlq_dir)
    await dlq._process_failed_messages()


def test_mark_permanent_failure_notified_adds_id(tmp_path) -> None:
    dlq_dir = tmp_path / "dlq"
    dlq_dir.mkdir()
    dlq = DeadLetterQueue(
        enqueue_fn=AsyncMock(),
        base_dir=dlq_dir,
        max_retries=1,
    )
    dlq.mark_permanent_failure_notified("delivery-1")
    assert "delivery-1" in dlq._permanent_failure_notified_ids


def test_dead_letter_queue_requires_storage_backend() -> None:
    with pytest.raises(ValueError, match="Either base_dir or storage_provider"):
        DeadLetterQueue(enqueue_fn=AsyncMock())


@pytest.mark.asyncio
async def test_dlq_retries_eligible_delivery(tmp_path) -> None:
    dlq_dir = tmp_path / "dlq"
    dlq_dir.mkdir()
    enqueue_mock = AsyncMock()

    dlq = DeadLetterQueue(
        enqueue_fn=enqueue_mock,
        base_dir=dlq_dir,
        max_retries=3,
        retry_intervals_ms=[0],
    )

    failed = QueuedDelivery(
        id="retry_me",
        channel="telegram",
        recipient="user1",
        content={"content": "hello"},
        enqueued_at=time.time(),
        priority=2,
        retry_count=0,
        last_attempt_at=time.time(),
        last_error="transient",
        failed_at=time.time(),
    )
    await move_to_failed(failed, base_dir=dlq_dir)
    await dlq._process_failed_messages()

    enqueue_mock.assert_awaited_once()
    assert await dlq.get_failed_count() == 0


@pytest.mark.asyncio
async def test_manual_retry_removes_failed_delivery(tmp_path) -> None:
    dlq_dir = tmp_path / "dlq"
    dlq_dir.mkdir()
    enqueue_mock = AsyncMock()

    dlq = DeadLetterQueue(
        enqueue_fn=enqueue_mock,
        base_dir=dlq_dir,
        max_retries=3,
    )

    failed = QueuedDelivery(
        id="manual_retry",
        channel="telegram",
        recipient="user1",
        content={"content": "hello"},
        enqueued_at=time.time(),
        priority=2,
        retry_count=0,
        failed_at=time.time(),
    )
    await move_to_failed(failed, base_dir=dlq_dir)
    assert await dlq.manual_retry("manual_retry") is True
    enqueue_mock.assert_awaited_once()
    assert await dlq.get_failed_count() == 0


@pytest.mark.asyncio
async def test_dlq_ttl_discards_notified_id_set(tmp_path) -> None:
    dlq_dir = tmp_path / "dlq"
    dlq_dir.mkdir()
    enqueue_mock = AsyncMock()

    dlq = DeadLetterQueue(
        enqueue_fn=enqueue_mock,
        base_dir=dlq_dir,
        ttl_days=1,
        max_retries=1,
    )
    dlq.mark_permanent_failure_notified("expired_msg")

    expired = QueuedDelivery(
        id="expired_msg",
        channel="telegram",
        recipient="user1",
        content={"content": "old"},
        enqueued_at=time.time() - (2 * 24 * 3600),
        priority=2,
        retry_count=1,
        failed_at=time.time() - (2 * 24 * 3600),
    )
    await move_to_failed(expired, base_dir=dlq_dir)
    await dlq._process_failed_messages()

    assert "expired_msg" not in dlq._permanent_failure_notified_ids
    assert await dlq.get_failed_count() == 0


@pytest.mark.asyncio
async def test_manual_retry_all_and_get_failed_deliveries(tmp_path) -> None:
    dlq_dir = tmp_path / "dlq"
    dlq_dir.mkdir()
    enqueue_mock = AsyncMock()

    dlq = DeadLetterQueue(
        enqueue_fn=enqueue_mock,
        base_dir=dlq_dir,
        max_retries=3,
    )

    for delivery_id in ("a", "b"):
        await move_to_failed(
            QueuedDelivery(
                id=delivery_id,
                channel="telegram",
                recipient="user1",
                content={"content": delivery_id},
                enqueued_at=time.time(),
                priority=2,
                retry_count=0,
                failed_at=time.time(),
            ),
            base_dir=dlq_dir,
        )

    assert len(await dlq.get_failed_deliveries()) == 2
    retried = await dlq.manual_retry_all()
    assert retried == 2
    assert enqueue_mock.await_count == 2


@pytest.mark.asyncio
async def test_manual_retry_missing_delivery_returns_false(tmp_path) -> None:
    dlq_dir = tmp_path / "dlq"
    dlq_dir.mkdir()
    dlq = DeadLetterQueue(enqueue_fn=AsyncMock(), base_dir=dlq_dir)
    assert await dlq.manual_retry("missing") is False
