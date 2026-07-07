"""Tests for DeadLetterQueue permanent-failure callback."""

from __future__ import annotations

import asyncio
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


@pytest.mark.asyncio
async def test_mark_permanent_failure_notified_persists_to_ledger(tmp_path) -> None:
    from myrm_agent_harness.infra.delivery.notification_ledger import InMemoryPermanentFailureNotificationLedger

    dlq_dir = tmp_path / "dlq"
    dlq_dir.mkdir()
    ledger = InMemoryPermanentFailureNotificationLedger()
    dlq = DeadLetterQueue(enqueue_fn=AsyncMock(), base_dir=dlq_dir, notification_ledger=ledger)

    dlq.mark_permanent_failure_notified("delivery-ledger")
    assert ledger.was_notified("delivery-ledger")


@pytest.mark.asyncio
async def test_dlq_start_and_stop(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    dlq_dir = tmp_path / "dlq"
    dlq_dir.mkdir()
    dlq = DeadLetterQueue(enqueue_fn=AsyncMock(), base_dir=dlq_dir)

    async def _cancel_sleep(_seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr("myrm_agent_harness.infra.delivery.dead_letter.asyncio.sleep", _cancel_sleep)
    await dlq.start()
    assert dlq._running is True
    assert dlq._retry_task is not None
    await dlq.stop()
    assert dlq._running is False


@pytest.mark.asyncio
async def test_process_failed_messages_noop_when_empty(tmp_path) -> None:
    dlq_dir = tmp_path / "dlq"
    dlq_dir.mkdir()
    dlq = DeadLetterQueue(enqueue_fn=AsyncMock(), base_dir=dlq_dir)
    await dlq._process_failed_messages()
    assert await dlq.get_failed_count() == 0


@pytest.mark.asyncio
async def test_dlq_permanent_failure_without_callback_marks_notified(tmp_path) -> None:
    dlq_dir = tmp_path / "dlq"
    dlq_dir.mkdir()
    dlq = DeadLetterQueue(enqueue_fn=AsyncMock(), base_dir=dlq_dir, max_retries=1)

    exhausted = QueuedDelivery(
        id="no_callback",
        channel="telegram",
        recipient="user1",
        content={"content": "hello"},
        enqueued_at=time.time(),
        priority=2,
        retry_count=1,
        last_error="send failed",
        failed_at=time.time(),
    )
    await move_to_failed(exhausted, base_dir=dlq_dir)
    await dlq._process_failed_messages()

    assert "no_callback" in dlq._permanent_failure_notified_ids


@pytest.mark.asyncio
async def test_dlq_retry_enqueue_failure_is_logged(tmp_path) -> None:
    dlq_dir = tmp_path / "dlq"
    dlq_dir.mkdir()
    enqueue_mock = AsyncMock(side_effect=RuntimeError("enqueue down"))

    dlq = DeadLetterQueue(
        enqueue_fn=enqueue_mock,
        base_dir=dlq_dir,
        max_retries=3,
        retry_intervals_ms=[0],
    )

    failed = QueuedDelivery(
        id="retry_fail",
        channel="telegram",
        recipient="user1",
        content={"content": "hello"},
        enqueued_at=time.time(),
        priority=2,
        retry_count=0,
        failed_at=time.time(),
    )
    await move_to_failed(failed, base_dir=dlq_dir)
    await dlq._process_failed_messages()

    assert await dlq.get_failed_count() == 1


@pytest.mark.asyncio
async def test_manual_retry_enqueue_failure_returns_false(tmp_path) -> None:
    dlq_dir = tmp_path / "dlq"
    dlq_dir.mkdir()
    enqueue_mock = AsyncMock(side_effect=RuntimeError("enqueue down"))
    dlq = DeadLetterQueue(enqueue_fn=enqueue_mock, base_dir=dlq_dir, max_retries=3)

    failed = QueuedDelivery(
        id="manual_fail",
        channel="telegram",
        recipient="user1",
        content={"content": "hello"},
        enqueued_at=time.time(),
        priority=2,
        retry_count=0,
        failed_at=time.time(),
    )
    await move_to_failed(failed, base_dir=dlq_dir)
    assert await dlq.manual_retry("manual_fail") is False


@pytest.mark.asyncio
async def test_manual_retry_all_continues_after_single_failure(tmp_path) -> None:
    dlq_dir = tmp_path / "dlq"
    dlq_dir.mkdir()
    enqueue_mock = AsyncMock(side_effect=[RuntimeError("first"), None])

    dlq = DeadLetterQueue(enqueue_fn=enqueue_mock, base_dir=dlq_dir, max_retries=3)

    for delivery_id in ("fail_one", "ok_one"):
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

    retried = await dlq.manual_retry_all()
    assert retried == 1
    assert await dlq.get_failed_count() == 1


@pytest.mark.asyncio
async def test_dlq_retry_loop_logs_processing_errors(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    dlq_dir = tmp_path / "dlq"
    dlq_dir.mkdir()
    dlq = DeadLetterQueue(enqueue_fn=AsyncMock(), base_dir=dlq_dir)
    dlq._running = True

    calls = 0

    async def _fail_once() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("process boom")

    monkeypatch.setattr(dlq, "_process_failed_messages", _fail_once)

    async def _instant_sleep(_seconds: float) -> None:
        dlq._running = False

    monkeypatch.setattr("myrm_agent_harness.infra.delivery.dead_letter.asyncio.sleep", _instant_sleep)
    await dlq._retry_loop()
    assert calls == 1


@pytest.mark.asyncio
async def test_dlq_ttl_delete_failure_keeps_delivery(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    dlq_dir = tmp_path / "dlq"
    dlq_dir.mkdir()
    dlq = DeadLetterQueue(enqueue_fn=AsyncMock(), base_dir=dlq_dir, ttl_days=1, max_retries=1)

    expired = QueuedDelivery(
        id="ttl_delete_fail",
        channel="telegram",
        recipient="user1",
        content={"content": "old"},
        enqueued_at=time.time() - (2 * 24 * 3600),
        priority=2,
        retry_count=1,
        failed_at=time.time() - (2 * 24 * 3600),
    )
    await move_to_failed(expired, base_dir=dlq_dir)

    async def _raise_delete(*_args: object, **_kwargs: object) -> None:
        raise OSError("delete failed")

    monkeypatch.setattr(
        "myrm_agent_harness.infra.delivery.dead_letter.delete_failed_delivery",
        _raise_delete,
    )
    await dlq._process_failed_messages()
    assert await dlq.get_failed_count() == 1

