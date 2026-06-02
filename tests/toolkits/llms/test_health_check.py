"""Tests for toolkits.llms.fallback.health_check — lightweight LLM health probing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.llms.fallback.health_check import (
    lightweight_health_check,
    lightweight_health_check_with_retry,
)


@pytest.mark.asyncio
class TestLightweightHealthCheck:
    async def test_healthy_model(self) -> None:
        llm = AsyncMock()
        llm.ainvoke.return_value = MagicMock(content="ok")
        result = await lightweight_health_check(llm, timeout_s=1.0)
        assert result is True
        llm.ainvoke.assert_called_once()

    async def test_timeout(self) -> None:
        llm = AsyncMock()
        llm.ainvoke.side_effect = TimeoutError("timed out")
        result = await lightweight_health_check(llm, timeout_s=1.0)
        assert result is False

    async def test_exception(self) -> None:
        llm = AsyncMock()
        llm.ainvoke.side_effect = RuntimeError("connection failed")
        result = await lightweight_health_check(llm, timeout_s=1.0)
        assert result is False

    async def test_empty_response(self) -> None:
        llm = AsyncMock()
        llm.ainvoke.return_value = None
        result = await lightweight_health_check(llm, timeout_s=1.0)
        assert result is False


@pytest.mark.asyncio
class TestLightweightHealthCheckWithRetry:
    async def test_first_attempt_success(self) -> None:
        llm = AsyncMock()
        llm.ainvoke.return_value = MagicMock(content="ok")
        result = await lightweight_health_check_with_retry(llm, max_attempts=3)
        assert result is True
        assert llm.ainvoke.call_count == 1

    async def test_retry_then_success(self) -> None:
        llm = AsyncMock()
        llm.ainvoke.side_effect = [RuntimeError("fail"), MagicMock(content="ok")]
        result = await lightweight_health_check_with_retry(llm, max_attempts=2)
        assert result is True
        assert llm.ainvoke.call_count == 2

    async def test_all_attempts_fail(self) -> None:
        llm = AsyncMock()
        llm.ainvoke.side_effect = RuntimeError("fail")
        result = await lightweight_health_check_with_retry(llm, max_attempts=2)
        assert result is False
        assert llm.ainvoke.call_count == 2
