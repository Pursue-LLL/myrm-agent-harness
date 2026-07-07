"""Tests for permanent-failure notification ledger integration in DeadLetterQueue."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest
from myrm_agent_harness.infra.delivery.dead_letter import DeadLetterQueue
from myrm_agent_harness.infra.delivery.notification_ledger import InMemoryPermanentFailureNotificationLedger
from myrm_agent_harness.infra.delivery.storage import QueuedDelivery, move_to_failed


@pytest.mark.asyncio
async def test_dlq_skips_callback_when_ledger_already_notified(tmp_path) -> None:
    dlq_dir = tmp_path / "dlq"
    dlq_dir.mkdir()
    callback = AsyncMock()
    ledger = InMemoryPermanentFailureNotificationLedger()
    ledger.mark_notified("ledger_notified")

    dlq = DeadLetterQueue(
        enqueue_fn=AsyncMock(),
        base_dir=dlq_dir,
        max_retries=1,
        on_permanent_failure=callback,
        notification_ledger=ledger,
    )

    exhausted = QueuedDelivery(
        id="ledger_notified",
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

    callback.assert_not_awaited()
