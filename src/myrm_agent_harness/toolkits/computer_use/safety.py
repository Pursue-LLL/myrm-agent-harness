"""Safety guardrails for desktop control tools."""

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

_BLOCKED_KEY_COMBOS: frozenset[frozenset[str]] = frozenset({
    frozenset({"cmd", "shift", "backspace"}),
    frozenset({"cmd", "option", "backspace"}),
    frozenset({"cmd", "ctrl", "q"}),
    frozenset({"cmd", "shift", "q"}),
    frozenset({"cmd", "option", "shift", "q"}),
})

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


def normalize_modifiers(modifiers: list[ModifierKey] | None) -> list[ModifierKey] | None:
    if not modifiers:
        return None
    return list(modifiers)
