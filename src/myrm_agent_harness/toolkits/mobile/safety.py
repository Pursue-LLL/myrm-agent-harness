"""Mobile safety guardrails and sensitive action barrier.

[INPUT]
- types::UIElementNode, MobileActionResult (POS: shared mobile types)

[OUTPUT]
- MobileSafetyGuard: Detects high-risk mobile screens and operations (payment, factory reset, lockscreen credentials)

[POS]
Security gate preventing unattended execution of destructive or high-risk mobile actions.
"""

from __future__ import annotations

import re
from typing import Final

# High-risk keywords in UI nodes (Chinese and English)
_HIGH_RISK_UI_KEYWORDS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"支付|付款|转账|确认付款|立即支付|输入支付密码|指纹支付", re.IGNORECASE),
    re.compile(r"恢复出厂设置|抹掉所有数据|格式化|清除全部数据|重置手机", re.IGNORECASE),
    re.compile(r"修改锁屏密码|修改支付密码|注销账号|关闭保护", re.IGNORECASE),
    re.compile(
        r"pay\s+now|confirm\s+payment|enter\s+pin|transfer\s+money|fingerprint\s+pay",
        re.IGNORECASE,
    ),
    re.compile(
        r"factory\s+reset|erase\s+all\s+data|wipe\s+data|reset\s+phone",
        re.IGNORECASE,
    ),
)

# High-risk package names
_SENSITIVE_PACKAGES: Final[frozenset[str]] = frozenset(
    {
        "com.eg.android.AlipayGphone",  # Alipay
        "com.tencent.mm.plugin.wallet",  # WeChat Pay
        "com.unionpay",  # UnionPay
        "com.android.settings.password",  # Security settings
    }
)


class MobileSafetyGuard:
    """Evaluates mobile UI state and actions for critical safety risks."""

    def __init__(self, allow_high_risk: bool = False) -> None:
        self.allow_high_risk = allow_high_risk

    def evaluate_ui_risk(
        self,
        current_package: str,
        elements: list[UIElementNode],
        raw_xml: str = "",
    ) -> tuple[bool, str | None]:
        """Check if current UI contains sensitive payment, credential or factory reset prompts.

        Returns:
            (is_risky, reason)
        """
        if self.allow_high_risk:
            return False, None

        if current_package in _SENSITIVE_PACKAGES:
            return True, f"Blocked interaction with high-security package '{current_package}'"

        # Check raw XML text or nodes
        for pattern in _HIGH_RISK_UI_KEYWORDS:
            if pattern.search(raw_xml):
                return (
                    True,
                    f"Sensitive action barrier triggered: high-risk prompt matching '{pattern.pattern}' detected.",
                )

        for el in elements:
            if el.password:
                return (
                    True,
                    "Sensitive action barrier triggered: secure password entry field detected.",
                )
            combined_text = f"{el.text} {el.content_desc}"
            for pattern in _HIGH_RISK_UI_KEYWORDS:
                if pattern.search(combined_text):
                    return (
                        True,
                        f"Sensitive action barrier triggered: high-risk element matching '{pattern.pattern}' detected.",
                    )

        return False, None

    def evaluate_command_risk(self, command: str) -> tuple[bool, str | None]:
        """Check if a raw shell command poses risk of device bricking or wipe."""
        if self.allow_high_risk:
            return False, None

        lower_cmd = command.lower()
        if "rm -rf" in lower_cmd or "reboot recovery" in lower_cmd or "reboot bootloader" in lower_cmd:
            return True, f"Dangerous command blocked: '{command}'"
        if "setprop" in lower_cmd and "secure" in lower_cmd:
            return True, f"System security property tampering blocked: '{command}'"

        return False, None
