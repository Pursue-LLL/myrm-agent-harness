"""SSOT for scanning text before persistence (Memory, Wiki raw/publish, display).

[POS]
See module docstring.
"""

from __future__ import annotations

import contextvars
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from myrm_agent_harness.core.security.detection.content_boundary import (
    has_invisible_unicode,
    strip_invisible_unicode,
)
from myrm_agent_harness.core.security.detection.harmful_state_detector import scan_for_harmful_states
from myrm_agent_harness.core.security.detection.instruction_shape import detect_instruction_shapes
from myrm_agent_harness.core.security.detection.leak_detector import (
    looks_like_password,
    redact_leaks,
    scan_for_leaks,
)
from myrm_agent_harness.core.security.detection.prompt_guard import scan_input

PseudonymizeFn = Callable[[str], str]

_pii_pseudonymizer_var: contextvars.ContextVar[PseudonymizeFn | None] = (
    contextvars.ContextVar("pii_pseudonymizer", default=None)
)


class PersistScanProfile(StrEnum):
    """Scan strictness for different persistence surfaces."""

    MEMORY_WRITE = "memory_write"
    WIKI_RAW = "wiki_raw"
    WIKI_PUBLISH = "wiki_publish"


class PersistScanVerdict(StrEnum):
    CLEAN = "clean"
    WARN = "warn"
    REDACTED = "redacted"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class PersistScanResult:
    verdict: PersistScanVerdict
    cleaned_text: str
    finding_codes: list[str] = field(default_factory=list)
    injection_score: float = 0.0
    injection_patterns: list[str] = field(default_factory=list)
    credential_patterns: list[str] = field(default_factory=list)
    instruction_shape_patterns: list[str] = field(default_factory=list)
    harmful_state_patterns: list[str] = field(default_factory=list)
    had_invisible_unicode: bool = False


def set_pii_pseudonymizer(fn: PseudonymizeFn | None) -> None:
    """Register PII pseudonymization for the current task context (Memory write path only).

    Stored in a ContextVar so fire-and-forget memory writes inherit the closure
    via ``asyncio.create_task`` context snapshot while run-end cleanup does not
    leak the closure across concurrently running tasks.
    """
    _pii_pseudonymizer_var.set(fn)


def get_pii_pseudonymizer() -> PseudonymizeFn | None:
    return _pii_pseudonymizer_var.get()


def sanitize_display_secrets(message: str, *, max_length: int = 240) -> str:
    """Redact credential fragments for user-visible error text."""
    cleaned = redact_leaks(message.strip())
    if len(cleaned) > max_length:
        return f"{cleaned[: max_length - 3]}..."
    return cleaned


def scan_persistable_content(
    text: str,
    *,
    profile: PersistScanProfile,
    block_threshold: float = 0.8,
    wiki_raw_caller: str | None = None,
) -> PersistScanResult:
    """Scan content before writing to a durable store."""
    if not text:
        return PersistScanResult(verdict=PersistScanVerdict.CLEAN, cleaned_text=text)

    cleaned = text
    verdict = PersistScanVerdict.CLEAN
    finding_codes: list[str] = []
    injection_score = 0.0
    injection_patterns: list[str] = []
    credential_patterns: list[str] = []
    instruction_shape_patterns: list[str] = []
    harmful_state_patterns: list[str] = []
    had_invisible = False

    if profile == PersistScanProfile.MEMORY_WRITE:
        harmful_matches = scan_for_harmful_states(text)
        if harmful_matches:
            return PersistScanResult(
                verdict=PersistScanVerdict.BLOCKED,
                cleaned_text=text,
                finding_codes=["harmful_state"],
                harmful_state_patterns=harmful_matches,
            )

    guard_result = scan_input(text)
    if not guard_result.safe:
        injection_score = guard_result.max_score
        injection_patterns = guard_result.patterns
        if profile == PersistScanProfile.MEMORY_WRITE and injection_score >= block_threshold:
            return PersistScanResult(
                verdict=PersistScanVerdict.BLOCKED,
                cleaned_text=text,
                finding_codes=["prompt_injection"],
                injection_score=injection_score,
                injection_patterns=injection_patterns,
            )
        if (
            profile == PersistScanProfile.WIKI_RAW
            and wiki_raw_caller == "agent"
            and injection_score >= block_threshold
        ):
            return PersistScanResult(
                verdict=PersistScanVerdict.BLOCKED,
                cleaned_text=text,
                finding_codes=["prompt_injection"],
                injection_score=injection_score,
                injection_patterns=injection_patterns,
            )
        if injection_patterns:
            verdict = PersistScanVerdict.WARN
            finding_codes.append("prompt_injection_warn")

    cred_matches = scan_for_leaks(text)
    if cred_matches:
        credential_patterns = cred_matches
        cleaned = redact_leaks(cleaned)
        verdict = PersistScanVerdict.REDACTED
        finding_codes.append("credential_redacted")

        if profile in {PersistScanProfile.WIKI_RAW, PersistScanProfile.WIKI_PUBLISH}:
            remaining = scan_for_leaks(cleaned)
            if remaining:
                return PersistScanResult(
                    verdict=PersistScanVerdict.BLOCKED,
                    cleaned_text=text,
                    finding_codes=["credential_unredactable"],
                    credential_patterns=credential_patterns,
                )

    if has_invisible_unicode(cleaned):
        had_invisible = True
        cleaned = strip_invisible_unicode(cleaned)
        if verdict == PersistScanVerdict.CLEAN:
            verdict = PersistScanVerdict.WARN
        finding_codes.append("invisible_unicode_stripped")

    shape_hits = detect_instruction_shapes(cleaned)
    if shape_hits:
        instruction_shape_patterns = [label.value for label in shape_hits]
        if verdict == PersistScanVerdict.CLEAN:
            verdict = PersistScanVerdict.WARN
        finding_codes.append("instruction_shape")

    password_hint = looks_like_password(cleaned)
    if password_hint is not None:
        cleaned = cleaned.replace(password_hint, "[REDACTED]")
        credential_patterns.append("password_like")
        verdict = PersistScanVerdict.REDACTED
        finding_codes.append("password_like_redacted")

    if profile == PersistScanProfile.MEMORY_WRITE:
        pseudonymizer = _pii_pseudonymizer_var.get()
        if pseudonymizer is not None:
            cleaned = pseudonymizer(cleaned)

    return PersistScanResult(
        verdict=verdict,
        cleaned_text=cleaned,
        finding_codes=finding_codes,
        injection_score=injection_score,
        injection_patterns=injection_patterns,
        credential_patterns=credential_patterns,
        instruction_shape_patterns=instruction_shape_patterns,
        harmful_state_patterns=harmful_state_patterns,
        had_invisible_unicode=had_invisible,
    )
