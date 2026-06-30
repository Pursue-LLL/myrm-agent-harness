"""Safety guardrails for desktop control tools.

Three guardrail types:
- Blocked key combos: prevents dangerous macOS system shortcuts
- Dangerous type-text patterns: prevents shell injection via typed text
- Sensitive app guard: prevents interaction with financial, communication,
  and password management applications
"""

from __future__ import annotations

import re

from myrm_agent_harness.toolkits.computer_use.types import ModifierKey

_KEY_ALIASES: dict[str, str] = {
    "command": "cmd",
    "control": "ctrl",
    "alt": "option",
    "meta": "cmd",
    "super": "cmd",
    "opt": "option",
}

_BLOCKED_KEY_COMBOS: frozenset[frozenset[str]] = frozenset(
    {
        frozenset({"cmd", "shift", "backspace"}),
        frozenset({"cmd", "option", "backspace"}),
        frozenset({"cmd", "ctrl", "q"}),
        frozenset({"cmd", "shift", "q"}),
        frozenset({"cmd", "option", "shift", "q"}),
    }
)

_DANGEROUS_TYPE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"curl\s+[^|]*\|\s*(?:ba)?sh", re.IGNORECASE),
    re.compile(r"wget\s+[^|]*\|\s*(?:ba)?sh", re.IGNORECASE),
    re.compile(r"\bsudo\s+rm\s+-[rf]", re.IGNORECASE),
    re.compile(r"\brm\s+-rf\s+(?:/|~/|\$HOME)", re.IGNORECASE),
    re.compile(r":\s*\(\)\s*\{[^}]*\}\s*;?\s*:", re.IGNORECASE),
)


def canonicalize_key_combo(keys: str) -> frozenset[str]:
    parts = [p.strip().lower() for p in re.split(r"\s*\+\s*", keys) if p.strip()]
    return frozenset(_KEY_ALIASES.get(part, part) for part in parts)


def is_blocked_key_combo(keys: str) -> str | None:
    canon = canonicalize_key_combo(keys)
    if canon in _BLOCKED_KEY_COMBOS:
        return f"Blocked dangerous key combination: {keys}"
    return None


def is_dangerous_type_text(text: str) -> str | None:
    for pattern in _DANGEROUS_TYPE_PATTERNS:
        if pattern.search(text):
            return f"Blocked dangerous text input matching pattern: {pattern.pattern}"
    return None


_SENSITIVE_APPS: frozenset[str] = frozenset(
    {
        # Financial
        "alipay", "\u652f\u4ed8\u5b9d",
        "bank", "\u94f6\u884c", "\u62db\u5546\u94f6\u884c", "\u5de5\u5546\u94f6\u884c", "\u5efa\u8bbe\u94f6\u884c", "\u519c\u4e1a\u94f6\u884c",
        "\u4ea4\u901a\u94f6\u884c", "\u4e2d\u4fe1\u94f6\u884c", "\u6c11\u751f\u94f6\u884c", "\u5174\u4e1a\u94f6\u884c",
        "\u540c\u82b1\u987a", "\u4e1c\u65b9\u8d22\u5bcc", "\u96ea\u7403",
        "chase", "wells fargo", "bank of america", "citi",
        # Communication / privacy
        "wechat", "\u5fae\u4fe1", "wecom", "\u4f01\u4e1a\u5fae\u4fe1",
        "telegram", "signal", "whatsapp",
        "\u9489\u9489", "dingtalk", "\u98de\u4e66", "feishu", "lark",
        # Password managers
        "1password", "bitwarden", "lastpass", "keepass", "dashlane",
        "keychain access", "\u94a5\u5319\u4e32\u8bbf\u95ee",
    }
)


def is_sensitive_app(
    app_name: str,
    window_title: str = "",
    custom_blocked: frozenset[str] | None = None,
    custom_allowed: frozenset[str] | None = None,
) -> str | None:
    """Check if the foreground app or window title matches the sensitive blocklist.

    Matches against both *app_name* and *window_title* to catch scenarios where
    sensitive content is opened inside a generic app (e.g. banking site in Chrome).

    Returns a human-readable block reason, or ``None`` if safe to proceed.
    """
    if not app_name:
        return None

    lower_name = app_name.lower()
    lower_title = window_title.lower() if window_title else ""

    if custom_allowed:
        if any(a.lower() in lower_name for a in custom_allowed):
            return None

    effective_blocked = _SENSITIVE_APPS | (custom_blocked or frozenset())
    for keyword in effective_blocked:
        kw = keyword.lower()
        if kw in lower_name:
            return (
                f"Blocked: Agent cannot interact with sensitive application '{app_name}'. "
                "Switch to a non-sensitive application to continue the task."
            )
        if lower_title and kw in lower_title:
            return (
                f"Blocked: Window title '{window_title}' indicates sensitive content "
                f"(matched '{keyword}'). Switch away to continue the task."
            )
    return None


def normalize_modifiers(modifiers: list[ModifierKey] | None) -> list[ModifierKey] | None:
    if not modifiers:
        return None
    return list(modifiers)
