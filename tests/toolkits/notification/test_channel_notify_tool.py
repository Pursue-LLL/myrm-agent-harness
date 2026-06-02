"""Unit tests for create_channel_notify_tool.

Covers:
- Empty body rejection
- No targets configured error
- Rate limit enforcement
- Body truncation
- Successful send
- Failed send error propagation
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.notification.tool import create_channel_notify_tool
from myrm_agent_harness.toolkits.notification.types import (
    NotifyResult,
    NotifyTarget,
    NotifyToolConfig,
)


class FakeSender:
    """Test double for NotificationSender."""

    def __init__(self, *, should_fail: bool = False, error: str = "") -> None:
        self._should_fail = should_fail
        self._error = error
        self.calls: list[tuple[NotifyTarget, str]] = []

    async def send(self, target: NotifyTarget, body: str) -> NotifyResult:
        self.calls.append((target, body))
        if self._should_fail:
            return NotifyResult(success=False, channel=target.channel, error=self._error)
        return NotifyResult(success=True, channel=target.channel)

    async def list_available_targets(self) -> list[NotifyTarget]:
        return []


@pytest.fixture
def single_target_config() -> NotifyToolConfig:
    return NotifyToolConfig(
        allowed_targets=(
            NotifyTarget(channel="telegram", recipient_id="chat_123", label="My TG"),
        ),
        rate_limit_per_session=3,
        max_body_length=100,
    )


@pytest.mark.asyncio
async def test_empty_body_rejected(single_target_config: NotifyToolConfig) -> None:
    sender = FakeSender()
    tool = create_channel_notify_tool(sender, single_target_config)
    result = await tool.ainvoke({"channel": "telegram", "target": "", "body": "   "})
    assert "empty" in result.lower()
    assert len(sender.calls) == 0


@pytest.mark.asyncio
async def test_no_targets_configured() -> None:
    config = NotifyToolConfig(allowed_targets=())
    sender = FakeSender()
    tool = create_channel_notify_tool(sender, config)
    result = await tool.ainvoke({"channel": "telegram", "target": "", "body": "hello"})
    assert "no notification targets configured" in result.lower()


@pytest.mark.asyncio
async def test_rate_limit_enforced(single_target_config: NotifyToolConfig) -> None:
    sender = FakeSender()
    tool = create_channel_notify_tool(sender, single_target_config)

    for _ in range(3):
        result = await tool.ainvoke({"channel": "", "target": "", "body": "msg"})
        assert "success" in result.lower()

    result = await tool.ainvoke({"channel": "", "target": "", "body": "over limit"})
    assert "rate limit" in result.lower()
    assert len(sender.calls) == 3


@pytest.mark.asyncio
async def test_body_truncation(single_target_config: NotifyToolConfig) -> None:
    sender = FakeSender()
    tool = create_channel_notify_tool(sender, single_target_config)
    long_body = "x" * 200
    await tool.ainvoke({"channel": "", "target": "", "body": long_body})
    assert len(sender.calls) == 1
    sent_body = sender.calls[0][1]
    assert len(sent_body) <= 100 + len("\n\n[...truncated]")
    assert sent_body.endswith("[...truncated]")


@pytest.mark.asyncio
async def test_successful_send(single_target_config: NotifyToolConfig) -> None:
    sender = FakeSender()
    tool = create_channel_notify_tool(sender, single_target_config)
    result = await tool.ainvoke({"channel": "telegram", "target": "chat_123", "body": "hello"})
    assert "success" in result.lower()
    assert "telegram" in result.lower()
    assert len(sender.calls) == 1
    assert sender.calls[0][0].recipient_id == "chat_123"


@pytest.mark.asyncio
async def test_failed_send_error(single_target_config: NotifyToolConfig) -> None:
    sender = FakeSender(should_fail=True, error="connection timeout")
    tool = create_channel_notify_tool(sender, single_target_config)
    result = await tool.ainvoke({"channel": "", "target": "", "body": "hello"})
    assert "error" in result.lower()
    assert "connection timeout" in result


@pytest.mark.asyncio
async def test_target_not_found(single_target_config: NotifyToolConfig) -> None:
    sender = FakeSender()
    tool = create_channel_notify_tool(sender, single_target_config)
    result = await tool.ainvoke({"channel": "discord", "target": "", "body": "hello"})
    assert "not found" in result.lower() or "not allowed" in result.lower()
    assert "telegram:chat_123" in result
    assert len(sender.calls) == 0
