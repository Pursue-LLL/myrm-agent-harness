"""reraise_if_cancelled: tell a stop aimed at this task apart from an absorbed cancellation."""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.utils.runtime.cancellation import reraise_if_cancelled


class TestReraiseIfCancelled:
    """reraise_if_cancelled: distinguish an SDK leak / cancelled child from a stop aimed here."""

    @pytest.mark.asyncio
    async def test_sdk_leak_returns_normally(self) -> None:
        """When the task is NOT externally cancelled, the function returns normally."""
        reraise_if_cancelled(asyncio.CancelledError())

    @pytest.mark.asyncio
    async def test_genuine_cancel_reraises(self) -> None:
        """When the task IS externally cancelled (.cancelling() > 0), re-raise."""

        async def _cancellable() -> None:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError as e:
                reraise_if_cancelled(e)

        task = asyncio.create_task(_cancellable())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_no_current_task_returns_normally(self) -> None:
        """Edge case: called outside an asyncio task context."""
        reraise_if_cancelled(asyncio.CancelledError())
