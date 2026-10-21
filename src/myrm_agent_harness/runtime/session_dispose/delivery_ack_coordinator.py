"""Delivery acknowledgement (ACK) coordinator for inter-agent communication.

Benchmarked against Omnigent commit a9e76345 delivery acknowledgement protocol:
- Tracks message dispatch and awaits acknowledgment from the recipient agent/process.
- Accurately measures round-trip time (RTT ms) for telemetry and slow-worker detection.
- Emits structured DeliveryAckReceipt records and diagnostic Markdown cards.
- Prevents silent delivery loss (the 'black-hole delivery' anti-pattern).

[OUTPUT]
- DeliveryAckCoordinator: Dispatches and verifies message delivery confirmations.

[INPUT]
- __future__
- time

[OUTPUT]
- DeliveryAckCoordinator

[POS]
Delivery acknowledgement (ACK) coordinator for inter-agent communication.
"""

from __future__ import annotations

import time

from myrm_agent_harness.runtime.session_dispose.dispose_ack_types import (
    DeliveryAckReceipt,
    DeliveryAckStatus,
)


class DeliveryAckCoordinator:
    """Coordinates and audits message delivery confirmations across distributed agents."""

    def __init__(self, default_timeout_seconds: float = 2.0) -> None:
        self.default_timeout = default_timeout_seconds
        # Mapping of (message_id, recipient_id) -> dispatch_timestamp
        self._in_flight_dispatches: dict[tuple[str, str], float] = {}

    def register_dispatch(self, message_id: str, recipient_id: str) -> None:
        """Register that a message has been sent to a recipient, awaiting delivery ACK."""
        key = (message_id, recipient_id)
        self._in_flight_dispatches[key] = time.time()

    def acknowledge_receipt(
        self,
        message_id: str,
        recipient_id: str,
        reason: str = "Delivery confirmed by recipient agent",
    ) -> DeliveryAckReceipt:
        """Record explicit receipt acknowledgement returned from recipient agent."""
        key = (message_id, recipient_id)
        dispatch_time = self._in_flight_dispatches.pop(key, None)

        now = time.time()
        rtt_ms = round((now - dispatch_time) * 1000.0, 2) if dispatch_time is not None else 0.0

        return DeliveryAckReceipt(
            message_id=message_id,
            recipient_id=recipient_id,
            status=DeliveryAckStatus.ACKNOWLEDGED,
            rtt_ms=rtt_ms,
            reason=reason,
            timestamp=now,
        )

    def check_timeout(
        self,
        message_id: str,
        recipient_id: str,
        custom_timeout_seconds: float | None = None,
    ) -> DeliveryAckReceipt | None:
        """Evaluate if an in-flight message has exceeded its ACK timeout window."""
        key = (message_id, recipient_id)
        dispatch_time = self._in_flight_dispatches.get(key)
        if dispatch_time is None:
            return None

        timeout_sec = custom_timeout_seconds if custom_timeout_seconds is not None else self.default_timeout
        now = time.time()
        elapsed = now - dispatch_time

        if elapsed >= timeout_sec:
            self._in_flight_dispatches.pop(key, None)
            return DeliveryAckReceipt(
                message_id=message_id,
                recipient_id=recipient_id,
                status=DeliveryAckStatus.TIMED_OUT,
                rtt_ms=round(elapsed * 1000.0, 2),
                reason=f"No delivery ACK received within {timeout_sec}s timeout window",
                timestamp=now,
            )

        return None

    def reject_receipt(
        self,
        message_id: str,
        recipient_id: str,
        reason: str = "Message delivery rejected by recipient target",
    ) -> DeliveryAckReceipt:
        """Record explicit rejection of message by recipient agent or dead process."""
        key = (message_id, recipient_id)
        dispatch_time = self._in_flight_dispatches.pop(key, None)
        now = time.time()
        rtt_ms = round((now - dispatch_time) * 1000.0, 2) if dispatch_time is not None else 0.0

        return DeliveryAckReceipt(
            message_id=message_id,
            recipient_id=recipient_id,
            status=DeliveryAckStatus.REJECTED,
            rtt_ms=rtt_ms,
            reason=reason,
            timestamp=now,
        )

    @staticmethod
    def render_ack_markdown_card(receipt: DeliveryAckReceipt) -> str:
        """Render a GitHub Flavored Markdown card summarizing message delivery status."""
        lines: list[str] = [
            "### 📨 跨智能体消息投递确认 (Delivery ACK) 卡片",
            f"- **消息 ID**: `{receipt.message_id}`",
            f"- **接收端 ID**: `{receipt.recipient_id}`",
            f"- **投递状态**: `{receipt.status.value.upper()}`",
            f"- **往返时延 (RTT)**: `{receipt.rtt_ms} ms`",
            f"- **状态说明**: {receipt.reason}",
            "",
        ]

        if receipt.status == DeliveryAckStatus.ACKNOWLEDGED:
            lines.extend(
                [
                    "> [!NOTE]",
                    "> 消息已成功送达接收端智能体，并收到物理 ACK 确认回执。",
                ]
            )
        elif receipt.status == DeliveryAckStatus.TIMED_OUT:
            lines.extend(
                [
                    "> [!WARNING]",
                    "> 消息在超时窗口内未收到任何 ACK 响应，可能遭遇网络断连或接收进程崩溃，请触发故障探测。",
                ]
            )
        else:
            lines.extend(
                [
                    "> [!CAUTION]",
                    "> 消息被接收端显式拒绝，请检查目标智能体权限与处理能力。",
                ]
            )

        return "\n".join(lines)
