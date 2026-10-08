"""Streaming reasoning continuation conduit for suspended headless execution.

[POS] src/myrm_agent_harness/core/security/headless_interactive_approval/continuation_conduit.py
[INPUT] myrm_agent_harness.core.security.headless_interactive_approval.types
[OUTPUT] StreamingContinuationConduit
"""

from __future__ import annotations

import logging
from typing import Final

from myrm_agent_harness.core.security.headless_interactive_approval.types import (
    ApprovalHoldStatus,
    ApprovalHoldTicket,
    StreamHoldChunk,
)

logger: Final[logging.Logger] = logging.getLogger(__name__)


class StreamingContinuationConduit:
    """Formats in-stream reasoning notices for suspended execution and seamless state continuation."""

    @staticmethod
    def format_hold_reasoning_block(ticket: ApprovalHoldTicket) -> StreamHoldChunk:
        """Format a markdown block to inject into the SSE reasoning buffer upon entering hold state."""
        markdown_notice = (
            f"\n\n> ⚠️ **[安全挂起 / Execution Suspended]** 正在请求执行高危操作:\n"
            f"> - **工具**: `{ticket.action.tool_name}`\n"
            f"> - **目标**: `{ticket.action.command_or_target}`\n"
            f"> - **风险等级**: `{ticket.action.risk_level}`\n"
            f">\n"
            f"> ✋ 依据安全策略，此操作需要人类授权。请点击以下安全短链进行一键审批:\n"
            f"> 🔗 **[点击一键安全审批 / Authorize Action]({ticket.shortlink_url})**\n\n"
        )

        return StreamHoldChunk(
            tx_id=ticket.tx_id,
            inject_markdown=markdown_notice,
            is_resumed=False,
            status=ticket.status,
        )

    @staticmethod
    def format_resumed_reasoning_block(ticket: ApprovalHoldTicket) -> StreamHoldChunk:
        """Format a continuation notice when a hold state is resolved (approved, rejected, or timed out)."""
        if ticket.status == ApprovalHoldStatus.APPROVED:
            notes = f" 备注: {ticket.operator_decision_notes}" if ticket.operator_decision_notes else ""
            resumed_text = (
                f"\n\n> ✅ **[审批已通过 / Action Approved]** 操作已由 `{ticket.decided_by or 'operator'}` 授权。{notes}\n"
                f"> 🚀 正在恢复沙箱执行并接续流式输出...\n\n"
            )
        elif ticket.status == ApprovalHoldStatus.REJECTED:
            notes = f" 拒绝理由: {ticket.operator_decision_notes}" if ticket.operator_decision_notes else ""
            resumed_text = (
                f"\n\n> 🛑 **[审批已拒绝 / Action Denied]** 操作已被 `{ticket.decided_by or 'operator'}` 明确拒绝。{notes}\n"
                f"> ⛔ 执行中止，返回安全降级响应。\n\n"
            )
        else:  # TIMED_OUT
            resumed_text = (
                "\n\n> ⏱️ **[审批已超时 / Action Timed Out]** 在时限内未收到人工授权响应。\n"
                "> 🔒 安全门禁自动生效，拒绝执行高危操作。\n\n"
            )

        return StreamHoldChunk(
            tx_id=ticket.tx_id,
            inject_markdown=resumed_text,
            is_resumed=True,
            status=ticket.status,
        )
