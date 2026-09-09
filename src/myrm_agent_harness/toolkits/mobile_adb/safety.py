"""Mobile safety guardrails and sensitive action barrier for Android Wireless ADB.

[INPUT]
- types::MobileUIElement, MobileActionResult (POS: domain models)

[OUTPUT]
- MobileSafetyGuard: Comprehensive zero-privilege gate preventing unintended payment, credential leakage,
  factory reset, sensitive settings access, or malicious ADB shell injection.

[POS]
myrm_agent_harness.toolkits.mobile_adb.safety
"""

from __future__ import annotations

import re
from typing import Final, TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.mobile_adb.types import MobileUIElement

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

# High-risk package names and activities (sensitive OS settings, payment, device admin)
_SENSITIVE_PACKAGES: Final[frozenset[str]] = frozenset(
    {
        "com.eg.android.alipaygphone",
        "com.tencent.mm.plugin.wallet",
        "com.unionpay",
        "com.android.settings.password",
        "com.google.android.gms.auth",
        "com.android.keychain",
    }
)

# Suspicious text input patterns that might leak credentials or run raw shell escapes
_BLOCKED_INPUT_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r";\s*rm\s+-rf", re.IGNORECASE),
    re.compile(r"`.*`"),
    re.compile(r"\$\(.*\)"),
)

# Hardware keys restricted from automated invocation
_RESTRICTED_HARDWARE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "POWER",
        "26",
        "KEYCODE_POWER",
        "FACTORY_RESET",
    }
)


class MobileSafetyGuard:
    """Evaluates mobile UI state, actions, and raw commands for critical safety risks."""

    def __init__(self, allow_high_risk: bool = False) -> None:
        self.allow_high_risk = allow_high_risk

    def is_package_allowed(self, package_name: str) -> tuple[bool, str]:
        """Check if an app package is safe to launch or interact with."""
        if self.allow_high_risk:
            return True, ""

        pkg_lower = package_name.lower().strip()
        if not pkg_lower:
            return True, ""

        for blocked in _SENSITIVE_PACKAGES:
            if blocked in pkg_lower:
                return False, f"Access to sensitive package '{package_name}' is blocked by security policy."

        return True, ""

    def is_input_safe(self, text: str) -> tuple[bool, str]:
        """Validate whether a text input string is safe to inject via adb input text."""
        if self.allow_high_risk:
            return True, ""

        for pattern in _BLOCKED_INPUT_PATTERNS:
            if pattern.search(text):
                return False, f"Input contains potentially malicious shell sequence: {text[:20]}"
        return True, ""

    def is_key_safe(self, keycode: str) -> tuple[bool, str]:
        """Check if a hardware key code is permitted."""
        if self.allow_high_risk:
            return True, ""

        if keycode.upper().strip() in _RESTRICTED_HARDWARE_KEYS:
            return False, f"Hardware key '{keycode}' is restricted for safety."
        return True, ""

    def evaluate_ui_risk(
        self,
        current_package: str,
        elements: list[MobileUIElement],
        raw_xml: str = "",
    ) -> tuple[bool, str | None]:
        """Check if current UI contains sensitive payment, credential or factory reset prompts.

        Returns:
            (is_risky, reason)
        """
        if self.allow_high_risk:
            return False, None

        allowed, reason = self.is_package_allowed(current_package)
        if not allowed:
            return True, reason

        # Check raw XML text or nodes
        for pattern in _HIGH_RISK_UI_KEYWORDS:
            if pattern.search(raw_xml):
                return (
                    True,
                    f"Sensitive action barrier triggered: high-risk prompt matching '{pattern.pattern}' detected.",
                )

        for el in elements:
            if getattr(el, "password", False):
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
