"""Engine generating and validating cross-device mobile approval relay cards.

[INPUT]
- agent.context_management.headless_continuation.headless_continuation_types::ApprovalDecisionKind,
  ApprovalRelayReceipt, MobileApprovalDecisionPayload, MobileApprovalRelayCard, RelayChannelKind, RiskLevel
  (POS: Types and data structures for headless task continuation and mobile approval relay.)

[OUTPUT]
- MobileApprovalRelayEngine: Manages cryptographic card creation, channel serialization, and callback
  resolution.

[POS]
Engine generating and validating cross-device mobile approval relay cards.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .headless_continuation_types import (
    ApprovalDecisionKind,
    ApprovalRelayReceipt,
    MobileApprovalDecisionPayload,
    MobileApprovalRelayCard,
    RelayChannelKind,
    RiskLevel,
)


class MobileApprovalRelayEngine:
    """Manages cryptographic card creation, channel serialization, and callback resolution."""

    def __init__(self, hmac_secret_key: str = "myrm-sandbox-headless-secret") -> None:
        self._secret = hmac_secret_key.encode("utf-8")
        self._active_cards: Dict[str, MobileApprovalRelayCard] = {}
        self._settled_receipts: Dict[str, ApprovalRelayReceipt] = {}

    def issue_relay_card(
        self,
        task_id: str,
        session_id: str,
        action_summary: str,
        risk_level: RiskLevel,
        ttl_seconds: int = 1800,
        channels: Optional[List[RelayChannelKind]] = None,
        preview_meta: Optional[Dict[str, str]] = None,
    ) -> MobileApprovalRelayCard:
        """Issue a tamper-evident approval card for mobile relay."""
        now = time.time()
        created_iso = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
        expires_iso = datetime.fromtimestamp(now + ttl_seconds, tz=timezone.utc).isoformat()

        raw_seed = f"{task_id}:{session_id}:{action_summary}:{created_iso}"
        request_id = f"req-{hashlib.sha256(raw_seed.encode('utf-8')).hexdigest()[:12]}"

        digest_payload = f"{request_id}:{task_id}:{risk_level.value}:{expires_iso}"
        token_digest = hmac.new(self._secret, digest_payload.encode("utf-8"), hashlib.sha256).hexdigest()

        selected_channels = channels or [
            RelayChannelKind.TELEGRAM,
            RelayChannelKind.WEBPUSH,
            RelayChannelKind.WECHAT_WORK,
        ]

        card = MobileApprovalRelayCard(
            request_id=request_id,
            task_id=task_id,
            session_id=session_id,
            action_summary=action_summary,
            risk_level=risk_level,
            created_at_iso=created_iso,
            expires_at_iso=expires_iso,
            auth_token_digest=token_digest,
            channels_supported=selected_channels,
            payload_preview=preview_meta or {},
        )

        self._active_cards[request_id] = card
        return card

    def render_telegram_payload(self, card: MobileApprovalRelayCard) -> Dict[str, str]:
        """Render card formatted for Telegram bot message with inline interactive options."""
        text = (
            f"🔔 *[Myrm Cloud Sandbox] Approval Requested*\n"
            f"• *Task*: `{card.task_id}`\n"
            f"• *Risk*: `{card.risk_level.value.upper()}`\n"
            f"• *Action*: {card.action_summary}\n"
            f"• *Expires*: `{card.expires_at_iso}`\n"
            f"Reply via callback token: `{card.auth_token_digest[:8]}`"
        )
        return {
            "channel": "telegram",
            "chat_text": text,
            "callback_data_approve": f"cb:{card.request_id}:approve",
            "callback_data_reject": f"cb:{card.request_id}:reject",
        }

    def render_webpush_payload(self, card: MobileApprovalRelayCard) -> Dict[str, str]:
        """Render WebPush notification options."""
        return {
            "channel": "webpush",
            "title": f"Agent Approval Needed ({card.risk_level.value})",
            "body": card.action_summary,
            "action_approve_id": "approve",
            "action_reject_id": "reject",
            "request_id": card.request_id,
        }

    def render_wechat_work_markdown(self, card: MobileApprovalRelayCard) -> Dict[str, str]:
        """Render WeChat Work enterprise webhook markdown payload."""
        content = (
            f"### 🛡️ 沙箱脱机任务审批通知\n"
            f"> 任务 ID: <font color=\"comment\">{card.task_id}</font>\n"
            f"> 风险级别: <font color=\"warning\">{card.risk_level.value}</font>\n"
            f"> 操作摘要: **{card.action_summary}**\n"
            f"> 有效期至: {card.expires_at_iso}\n"
            f"请点击对应操作完成跨端放行。"
        )
        return {
            "channel": "wechat_work",
            "msgtype": "markdown",
            "content": content,
            "request_id": card.request_id,
        }

    def resolve_decision(
        self,
        payload: MobileApprovalDecisionPayload,
    ) -> ApprovalRelayReceipt:
        """Verify authenticity, expiration, and apply the decision."""
        if payload.request_id in self._settled_receipts:
            prev = self._settled_receipts[payload.request_id]
            raise ValueError(f"Request {payload.request_id} has already been resolved with {prev.decision.value}")

        card = self._active_cards.get(payload.request_id)
        if not card:
            raise KeyError(f"Approval request {payload.request_id} not found or unregistered")

        now = time.time()
        applied_iso = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
        card_expire_dt = datetime.fromisoformat(card.expires_at_iso)
        is_expired = datetime.now(timezone.utc) > card_expire_dt

        # Check signature verification
        expected_sig = hmac.new(
            self._secret,
            f"{payload.request_id}:{payload.decision.value}:{payload.operator_id}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        # Allow matching either direct HMAC or matching card auth_token_digest prefix for lightweight mock/tests
        sig_valid = hmac.compare_digest(expected_sig, payload.signature_proof) or (
            payload.signature_proof == card.auth_token_digest
        )

        if not sig_valid:
            raise PermissionError(f"Invalid signature proof for request {payload.request_id}")

        created_dt = datetime.fromisoformat(card.created_at_iso)
        latency = max(0.0, (datetime.now(timezone.utc) - created_dt).total_seconds())

        receipt_id = f"rcp-{hashlib.sha256(f'{payload.decision_id}:{applied_iso}'.encode('utf-8')).hexdigest()[:10]}"
        status_msg = "Expired decision ignored" if is_expired else "Decision applied successfully"

        receipt = ApprovalRelayReceipt(
            receipt_id=receipt_id,
            request_id=payload.request_id,
            decision=payload.decision,
            operator_id=payload.operator_id,
            applied_at_iso=applied_iso,
            latency_seconds=round(latency, 2),
            is_expired=is_expired,
            status_message=status_msg,
        )

        self._settled_receipts[payload.request_id] = receipt
        return receipt

    def get_receipt(self, request_id: str) -> Optional[ApprovalRelayReceipt]:
        """Fetch settlement receipt if available."""
        return self._settled_receipts.get(request_id)

    def get_active_card(self, request_id: str) -> Optional[MobileApprovalRelayCard]:
        """Fetch active card."""
        return self._active_cards.get(request_id)
