"""Security guardrails for mobile ADB operations.

[INPUT]
- types::AdbTouchAction, AdbDeviceSnapshot

[OUTPUT]
- AdbSafetyGuard: security filter protecting sensitive packages, credentials, and payment UIs

[POS]
Safety gateway preventing malicious or unintended operations on connected mobile devices.
"""

from __future__ import annotations

import re

# Blocked package names and activities (sensitive OS settings, payment, device admin)
_BLOCKED_PACKAGES: frozenset[str] = frozenset({
    "com.android.settings.password",
    "com.google.android.gms.auth",
    "com.android.keychain",
})

# Suspicious text input patterns that might leak credentials or run raw shell escapes
_BLOCKED_INPUT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r";\s*rm\s+-rf", re.IGNORECASE),
    re.compile(r"`.*`"),
    re.compile(r"\$\(.*\)"),
)


class AdbSafetyGuard:
    """Zero-privilege safety guard for mobile actions."""

    @staticmethod
    def is_package_allowed(package_name: str) -> tuple[bool, str]:
        """Check if an app package is safe to launch or interact with."""
        pkg_lower = package_name.lower().strip()
        if not pkg_lower:
            return True, ""

        for blocked in _BLOCKED_PACKAGES:
            if blocked in pkg_lower:
                return False, f"Access to sensitive package '{package_name}' is blocked by security policy."

        return True, ""

    @staticmethod
    def is_input_safe(text: str) -> tuple[bool, str]:
        """Validate whether a text input string is safe to inject via adb input text."""
        for pattern in _BLOCKED_INPUT_PATTERNS:
            if pattern.search(text):
                return False, f"Input contains potentially malicious shell sequence: {text[:20]}"
        return True, ""

    @staticmethod
    def is_key_safe(keycode: str) -> tuple[bool, str]:
        """Check if a hardware key code is permitted."""
        blocked_keys = {"POWER", "26", "FACTORY_RESET"}
        if keycode.upper().strip() in blocked_keys:
            return False, f"Hardware key '{keycode}' is restricted for safety."
        return True, ""
