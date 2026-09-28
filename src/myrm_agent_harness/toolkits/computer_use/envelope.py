"""Intent envelope and boundary guard for computer use toolkit.

[INPUT]
- (none)

[OUTPUT]
- IntentEnvelopeSpec, WindowHierarchyContext, EnvelopeCheckResult, KeystrokeSanitizer, check_envelope_action

[POS]
Generic, framework-agnostic intent envelope contracts and keystroke sanitization
for scoped, non-interruptive desktop action execution.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

_SYSTEM_DIALOG_BUNDLE_IDS: frozenset[str] = frozenset({
    "com.apple.appkit.xpc.openandsavepanelservice",
    "com.apple.finder",
    "com.apple.securityui",
    "com.apple.coreauthui",
})

_DEFAULT_HIGH_RISK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\brm\s+-(?:r|f|rf|fr)\s+[/~]", re.IGNORECASE),
    re.compile(r"\b(?:mkfs|dd\s+if=|fdisk|format\s+[a-z]:)", re.IGNORECASE),
    re.compile(r":\(\)\s*\{\s*:\|:&\s*\};:", re.IGNORECASE),
    re.compile(r"(?:curl|wget)\s+[^|\n]+\|\s*(?:bash|sh|zsh)", re.IGNORECASE),
    re.compile(r"\bchmod\s+-R\s+777\s+[/~]", re.IGNORECASE),
    re.compile(r"\b(?:shutdown|reboot|init\s+0)\b", re.IGNORECASE),
)

_DANGEROUS_HOTKEY_COMBOS: tuple[frozenset[str], ...] = (
    # Mac empty trash without confirmation
    frozenset({"command", "shift", "delete"}),
    frozenset({"command", "shift", "backspace"}),
    frozenset({"cmd", "shift", "delete"}),
    frozenset({"cmd", "shift", "backspace"}),
    # Force quit applications
    frozenset({"command", "option", "escape"}),
    frozenset({"command", "alt", "escape"}),
    frozenset({"cmd", "option", "escape"}),
    frozenset({"cmd", "alt", "escape"}),
    frozenset({"command", "option", "esc"}),
    frozenset({"cmd", "alt", "esc"}),
    # Windows / Linux interrupts & hard task termination
    frozenset({"ctrl", "alt", "delete"}),
    frozenset({"ctrl", "alt", "del"}),
    frozenset({"control", "alt", "delete"}),
    frozenset({"control", "alt", "del"}),
    frozenset({"alt", "f4"}),
    frozenset({"ctrl", "alt", "backspace"}),
)


@dataclass(frozen=True)
class WindowHierarchyContext:
    """Window context representing active application and window hierarchy."""

    app_name: str = ""
    app_id: str = ""
    window_title: str = ""
    parent_app_id: str | None = None
    is_system_dialog: bool = False

    def is_system_modal(self) -> bool:
        """Return True if this window is a known system sheet or picker."""
        if self.is_system_dialog:
            return True
        norm_id = self.app_id.strip().lower()
        return norm_id in _SYSTEM_DIALOG_BUNDLE_IDS or "openandsave" in norm_id


@dataclass
class IntentEnvelopeSpec:
    """Execution boundary envelope declared for a scoped task."""

    task_id: str
    allowed_app_names: tuple[str, ...] = ()
    allowed_app_ids: tuple[str, ...] = ()
    max_actions: int = 30
    used_actions: int = 0
    idle_timeout_seconds: float = 180.0
    allow_system_dialogs: bool = True
    forbidden_commands: tuple[str, ...] = ()

    def is_budget_exhausted(self) -> bool:
        """Return True if the action budget has been fully consumed."""
        return self.used_actions >= self.max_actions

    def remaining_budget(self) -> int:
        """Return remaining action count."""
        return max(0, self.max_actions - self.used_actions)


@dataclass(frozen=True)
class EnvelopeCheckResult:
    """Result of checking an action against the active intent envelope."""

    allowed: bool
    reason: Literal[
        "ok",
        "out_of_boundary",
        "budget_exhausted",
        "keystroke_violation",
        "system_dialog_parent_untrusted",
        "idle_timeout",
    ]
    detail: str = ""


class KeystrokeSanitizer:
    """Static inspector for keystroke commands and input text."""

    @classmethod
    def inspect(cls, text: str) -> tuple[bool, str]:
        """Inspect text input for known high-risk destructive commands.

        Returns:
            (is_safe, violation_reason)
        """
        if not text or not text.strip():
            return True, ""

        for pattern in _DEFAULT_HIGH_RISK_PATTERNS:
            if pattern.search(text):
                return False, f"Dangerous command detected: {pattern.pattern}"

        return True, ""

    @classmethod
    def inspect_hotkey(cls, keys: Sequence[str] | str) -> tuple[bool, str]:
        """Inspect key combo for known destructive system actions (e.g. empty trash, force kill).

        Returns:
            (is_safe, violation_reason)
        """
        if not keys:
            return True, ""

        if isinstance(keys, str):
            tokens = {part.strip().lower() for part in re.split(r"[\s\+\-_,]+", keys) if part.strip()}
        else:
            tokens = {str(k).strip().lower() for k in keys if str(k).strip()}

        if not tokens:
            return True, ""

        for dangerous_combo in _DANGEROUS_HOTKEY_COMBOS:
            if dangerous_combo.issubset(tokens):
                combo_str = "+".join(sorted(dangerous_combo))
                return False, f"Dangerous system hotkey detected: {combo_str}"

        return True, ""


def check_envelope_action(
    *,
    envelope: IntentEnvelopeSpec,
    window: WindowHierarchyContext,
    text_to_type: str = "",
    keys_to_press: Sequence[str] | str | None = None,
) -> EnvelopeCheckResult:
    """Evaluate whether an action is permitted within the given envelope."""
    if envelope.is_budget_exhausted():
        return EnvelopeCheckResult(
            allowed=False,
            reason="budget_exhausted",
            detail=f"Budget exhausted ({envelope.used_actions}/{envelope.max_actions})",
        )

    if text_to_type:
        is_safe, violation = KeystrokeSanitizer.inspect(text_to_type)
        if not is_safe:
            return EnvelopeCheckResult(
                allowed=False,
                reason="keystroke_violation",
                detail=violation,
            )
        is_safe_key, key_violation = KeystrokeSanitizer.inspect_hotkey(text_to_type)
        if not is_safe_key:
            return EnvelopeCheckResult(
                allowed=False,
                reason="keystroke_violation",
                detail=key_violation,
            )

    if keys_to_press:
        is_safe_key, key_violation = KeystrokeSanitizer.inspect_hotkey(keys_to_press)
        if not is_safe_key:
            return EnvelopeCheckResult(
                allowed=False,
                reason="keystroke_violation",
                detail=key_violation,
            )

    norm_target_id = window.app_id.strip().lower()
    norm_target_name = window.app_name.strip().lower()

    allowed_ids = {item.strip().lower() for item in envelope.allowed_app_ids if item.strip()}
    allowed_names = {item.strip().lower() for item in envelope.allowed_app_names if item.strip()}

    if window.is_system_modal() and envelope.allow_system_dialogs:
        if window.parent_app_id:
            norm_parent = window.parent_app_id.strip().lower()
            if norm_parent in allowed_ids or any(name in norm_parent for name in allowed_names):
                return EnvelopeCheckResult(allowed=True, reason="ok")
            return EnvelopeCheckResult(
                allowed=False,
                reason="system_dialog_parent_untrusted",
                detail=f"System dialog parent {window.parent_app_id} is untrusted",
            )
        return EnvelopeCheckResult(allowed=True, reason="ok")

    if norm_target_id and norm_target_id in allowed_ids:
        return EnvelopeCheckResult(allowed=True, reason="ok")

    if norm_target_name:
        if norm_target_name in allowed_names:
            return EnvelopeCheckResult(allowed=True, reason="ok")
        for target in allowed_names:
            if len(target) >= 3:
                pattern = rf"\b{re.escape(target)}\b"
                if re.search(pattern, norm_target_name):
                    return EnvelopeCheckResult(allowed=True, reason="ok")

    return EnvelopeCheckResult(
        allowed=False,
        reason="out_of_boundary",
        detail=f"App {window.app_name} ({window.app_id}) is outside envelope",
    )
