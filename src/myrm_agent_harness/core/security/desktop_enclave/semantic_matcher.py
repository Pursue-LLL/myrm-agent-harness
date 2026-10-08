"""High-precision semantic risk matcher for computer-use desktop actions.

[INPUT]
- CriticalDesktopAction (coordinates, target_element_text, semantic_intent, payload_text)

[OUTPUT]
- CriticalActionSemanticMatcher: Classifies action into SAFE, SUSPICIOUS, or CRITICAL risk tier

[POS]
Harness core security matcher. Detects dangerous GUI button clicks (payment, deletion,
messaging, disk formatting) before physical mouse/keyboard events are emitted.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.desktop_enclave.types import (
    CriticalDesktopAction,
    DesktopActionRiskLevel,
)

# High-risk semantic patterns categorized by operational risk
_FINANCIAL_PATTERNS: tuple[str, ...] = (
    "支付",
    "付款",
    "转账",
    "确认购买",
    "立即下单",
    "充值",
    "pay",
    "checkout",
    "transfer",
    "buy now",
    "confirm payment",
    "wire transfer",
)

_DESTRUCTIVE_PATTERNS: tuple[str, ...] = (
    "清空回收站",
    "删除并清空",
    "永久删除",
    "格式化",
    "抹掉",
    "empty trash",
    "empty recycle bin",
    "delete permanently",
    "format disk",
    "erase all content",
    "rm -rf",
    "drop database",
)

_OUTBOUND_MESSAGING_PATTERNS: tuple[str, ...] = (
    "发送消息给",
    "群发",
    "发送给所有人",
    "send message to",
    "blast email",
    "broadcast to",
)

_SYSTEM_SECURITY_PATTERNS: tuple[str, ...] = (
    "关闭防火墙",
    "禁用安全保护",
    "disable security",
    "disable sip",
    "disable antivirus",
    "chmod 777 /",
)


class CriticalActionSemanticMatcher:
    """Evaluates GUI element texts, payloads, and intents against critical risk heuristics."""

    @classmethod
    def evaluate(cls, action: CriticalDesktopAction) -> tuple[DesktopActionRiskLevel, str, str]:
        """Classify the risk level of a desktop action.

        Returns:
            tuple of (risk_level, matched_category, reason)
        """
        combined_text = " ".join(
            filter(
                None,
                [
                    action.target_element_text,
                    action.semantic_intent,
                    action.payload_text,
                ],
            )
        ).lower()

        # 1. Financial & Payment actions
        for kw in _FINANCIAL_PATTERNS:
            if kw in combined_text:
                return (
                    DesktopActionRiskLevel.CRITICAL,
                    "financial_transaction",
                    f"Impending action triggers financial or purchase operation: matched '{kw}'",
                )

        # 2. Destructive data loss
        for kw in _DESTRUCTIVE_PATTERNS:
            if kw in combined_text:
                return (
                    DesktopActionRiskLevel.CRITICAL,
                    "destructive_deletion",
                    f"Impending action threatens permanent data loss or deletion: matched '{kw}'",
                )

        # 3. Outbound broadcast/messaging
        for kw in _OUTBOUND_MESSAGING_PATTERNS:
            if kw in combined_text:
                return (
                    DesktopActionRiskLevel.CRITICAL,
                    "outbound_messaging",
                    f"Impending action sends external communication: matched '{kw}'",
                )

        # 4. System security configuration
        for kw in _SYSTEM_SECURITY_PATTERNS:
            if kw in combined_text:
                return (
                    DesktopActionRiskLevel.CRITICAL,
                    "system_security_tamper",
                    f"Impending action tampers with OS security policies: matched '{kw}'",
                )

        # Suspicious keywords
        if "delete" in combined_text or "删除" in combined_text or "modify" in combined_text:
            return (
                DesktopActionRiskLevel.SUSPICIOUS,
                "general_mutation",
                "Action involves file or data modification",
            )

        return (
            DesktopActionRiskLevel.SAFE,
            "benign",
            "Action exhibits no high-risk operational keywords",
        )
