"""Mobile security barrier protecting against dangerous operations on Android devices.

[INPUT]
- types::MobileHierarchy, SensitiveActionVerdict, TouchAction

[OUTPUT]
- MobileSafetyBarrier: Guard that blocks or requires human approval for payment, authentication, or factory reset actions

[POS]
Security gatekeeper for mobile automation in toolkits/mobile.
"""

from __future__ import annotations

import re

from myrm_agent_harness.toolkits.mobile.protocols import MobileSafetyBarrierProtocol
from myrm_agent_harness.toolkits.mobile.types import (
    MobileHierarchy,
    SensitiveActionVerdict,
    TouchAction,
)

# High-risk keywords for critical sensitive actions
CRITICAL_PATTERNS = [
    r"支付密码|输入密码|确认支付|微信支付|支付宝支付|银行卡号|CVV|安全码",
    r"恢复出厂设置|清除所有数据|格式化|erase all data|factory reset",
    r"指纹录入|人脸录入|锁定设备|修改锁屏密码|device admin|设备管理器",
]

# Medium-risk keywords that warrant warning or confirmation
MEDIUM_RISK_PATTERNS = [
    r"授权登录|允许访问通讯录|允许访问位置|允许读取短信|root privilege|su permission",
    r"转账|充值|购买|立即付款|pay now|checkout|transfer money",
    r"卸载应用|清除数据|force stop",
]


class MobileSafetyBarrier(MobileSafetyBarrierProtocol):
    """Runtime safety barrier for mobile ADB interactions."""

    def __init__(self, strict_mode: bool = True) -> None:
        self.strict_mode = strict_mode
        self._compiled_critical = [re.compile(p, re.IGNORECASE) for p in CRITICAL_PATTERNS]
        self._compiled_medium = [re.compile(p, re.IGNORECASE) for p in MEDIUM_RISK_PATTERNS]

    def evaluate_hierarchy(self, hierarchy: MobileHierarchy) -> SensitiveActionVerdict:
        """Scan active UI hierarchy for sensitive input fields and security screens."""
        matched: list[str] = []
        is_password_screen = False

        def _scan_node(node: object) -> None:
            nonlocal is_password_screen
            # Check node password attribute
            if getattr(node, "password", False):
                is_password_screen = True
                matched.append("PasswordInputField")

            text = f"{getattr(node, 'text', '')} {getattr(node, 'content_desc', '')} {getattr(node, 'resource_id', '')}"
            for pattern in self._compiled_critical:
                if pattern.search(text):
                    matched.append(f"CriticalKeyword:{pattern.pattern}")
            for pattern in self._compiled_medium:
                if pattern.search(text):
                    matched.append(f"MediumKeyword:{pattern.pattern}")

            for child in getattr(node, "children", []):
                _scan_node(child)

        for root in hierarchy.root_nodes:
            _scan_node(root)

        if is_password_screen or any("CriticalKeyword" in m for m in matched):
            return SensitiveActionVerdict(
                is_sensitive=True,
                risk_level="CRITICAL",
                matched_patterns=matched,
                reason="Screen contains password input or critical security/payment action",
                requires_confirmation=True,
            )

        if any("MediumKeyword" in m for m in matched):
            return SensitiveActionVerdict(
                is_sensitive=True,
                risk_level="MEDIUM",
                matched_patterns=matched,
                reason="Screen contains permissions, payment or destructive intent",
                requires_confirmation=self.strict_mode,
            )

        return SensitiveActionVerdict(
            is_sensitive=False,
            risk_level="LOW",
            matched_patterns=[],
            reason="Screen passed safety evaluation",
            requires_confirmation=False,
        )

    def evaluate_action(
        self,
        action: TouchAction | str,
        target_text: str = "",
        target_package: str = "",
    ) -> SensitiveActionVerdict:
        """Evaluate specific target action intent."""
        combined = f"{target_text} {target_package}"
        matched: list[str] = []

        for pattern in self._compiled_critical:
            if pattern.search(combined):
                matched.append(f"CriticalAction:{pattern.pattern}")

        if matched:
            return SensitiveActionVerdict(
                is_sensitive=True,
                risk_level="CRITICAL",
                matched_patterns=matched,
                reason=f"Action '{action}' targets critical keyword/package: {combined}",
                requires_confirmation=True,
            )

        for pattern in self._compiled_medium:
            if pattern.search(combined):
                matched.append(f"MediumAction:{pattern.pattern}")

        if matched:
            return SensitiveActionVerdict(
                is_sensitive=True,
                risk_level="MEDIUM",
                matched_patterns=matched,
                reason=f"Action '{action}' targets sensitive keyword: {combined}",
                requires_confirmation=self.strict_mode,
            )

        return SensitiveActionVerdict(
            is_sensitive=False,
            risk_level="LOW",
            matched_patterns=[],
            reason="Action passed safety evaluation",
            requires_confirmation=False,
        )
