"""Unit tests for gate guard denial path Unicode sanitization suite."""

from __future__ import annotations

from myrm_agent_harness.core.security.denial_sanitizer import (
    DenialSanitizeResult,
    SpoofRiskLevel,
    sanitize_denial_message,
    sanitize_denial_payload,
)


def test_clean_denial_message() -> None:
    text = "Action blocked: Access to /etc/shadow is forbidden."
    result: DenialSanitizeResult = sanitize_denial_message(text)

    assert result.original_text == text
    assert result.sanitized_text == text
    assert result.invisible_codepoints_removed == 0
    assert result.has_bidi_controls is False
    assert result.spoof_risk == SpoofRiskLevel.NONE
    assert len(result.removed_characters) == 0


def test_empty_denial_message() -> None:
    result = sanitize_denial_message("")

    assert result.original_text == ""
    assert result.sanitized_text == ""
    assert result.invisible_codepoints_removed == 0
    assert result.has_bidi_controls is False
    assert result.spoof_risk == SpoofRiskLevel.NONE
    assert len(result.removed_characters) == 0


def test_denial_message_with_invisible_characters() -> None:
    # Contains zero-width space (\u200B) and BOM (\uFEFF)
    malicious = "Access denied\u200B to sensitive\uFEFF path."
    result = sanitize_denial_message(malicious)

    assert result.original_text == malicious
    assert result.sanitized_text == "Access denied to sensitive path."
    assert result.invisible_codepoints_removed == 2
    assert result.has_bidi_controls is False
    assert result.spoof_risk == SpoofRiskLevel.LOW
    assert "U+200B" in result.removed_characters
    assert "U+FEFF" in result.removed_characters


def test_denial_message_with_bidi_override() -> None:
    # Contains Right-to-Left Override (\u202E) attempting visual spoofing
    spoofed = "Denied: command [cat \u202Eexe.txt\u202C] was blocked"
    result = sanitize_denial_message(spoofed)

    assert result.sanitized_text == "Denied: command [cat exe.txt] was blocked"
    assert result.has_bidi_controls is True
    assert result.spoof_risk == SpoofRiskLevel.HIGH
    assert "U+202E" in result.removed_characters
    assert "U+202C" in result.removed_characters


def test_sanitize_denial_payload_dict() -> None:
    payload: dict[str, str] = {
        "reason": "Security \u200Bviolation",
        "detail": "Blocked \u202Eaction\u202C target",
        "clean_field": "Normal error message",
    }
    sanitized: dict[str, str] = sanitize_denial_payload(payload)

    assert sanitized["reason"] == "Security violation"
    assert sanitized["detail"] == "Blocked action target"
    assert sanitized["clean_field"] == "Normal error message"
