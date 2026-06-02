"""Tests for MCP error handling utilities (anyio CancelledError safety)."""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.toolkits.mcp.errors import reraise_if_genuine_cancel


class TestReraiseIfGenuineCancel:
    """reraise_if_genuine_cancel: distinguish SDK leaks from real cancellations."""

    @pytest.mark.asyncio
    async def test_sdk_leak_returns_normally(self) -> None:
        """When the task is NOT externally cancelled, the function returns normally."""
        exc = asyncio.CancelledError()
        reraise_if_genuine_cancel(exc)

    @pytest.mark.asyncio
    async def test_genuine_cancel_reraises(self) -> None:
        """When the task IS externally cancelled (.cancelling() > 0), re-raise."""

        async def _cancellable() -> None:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError as e:
                reraise_if_genuine_cancel(e)

        task = asyncio.create_task(_cancellable())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_no_current_task_returns_normally(self) -> None:
        """Edge case: called outside an asyncio task context."""
        exc = asyncio.CancelledError()
        reraise_if_genuine_cancel(exc)
