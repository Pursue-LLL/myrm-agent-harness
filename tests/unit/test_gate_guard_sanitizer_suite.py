"""Comprehensive test suite for GateGuard invisible Unicode sanitization.

[INPUT]
- Untrusted file paths and denial reason strings containing malicious Unicode.

[OUTPUT]
- Verified sanitization behavior aligned with ECC #3103 and CI Unicode safety policy.

[POS]
- Harness unit test suite for denial path Unicode sanitization.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.gate_guard_sanitizer import (
    DenialSanitizePolicy,
    GateGuardDenialSanitizer,
    InvisibleUnicodeCategory,
    classify_codepoint,
    detect_categories,
    sanitize_denial_path,
    sanitize_denial_reason,
)


def test_ecc_regression_dangerous_invisible_in_denial_paths() -> None:
    """Exact regression test matching ECC #3103 (commit bf70150e)."""
    file_path = (
        "/src/eu2028\u2028eu2029\u2029app.js\u200bhidden\u2060name\ufefftail\u3164x\u0091c1.js"
    )

    sanitizer = GateGuardDenialSanitizer()
    res = sanitizer.sanitize_path(file_path)

    bad_chars = ["\u2028", "\u2029", "\u200b", "\u2060", "\ufeff", "\u3164", "\u0091"]
    for bad in bad_chars:
        assert bad not in res.sanitized_text, (
            f"Denial path must not carry U+{ord(bad):04X} ({bad})"
        )

    # Visible path components must remain intact
    for expected in ["app.js", "hidden", "name", "tail", "c1.js"]:
        assert expected in res.sanitized_text

    assert res.characters_removed_count >= len(bad_chars)
    assert res.has_modifications is True
    assert InvisibleUnicodeCategory.LINE_SEPARATOR in res.categories_detected
    assert InvisibleUnicodeCategory.ZERO_WIDTH in res.categories_detected
    assert InvisibleUnicodeCategory.WORD_JOINER in res.categories_detected
    assert InvisibleUnicodeCategory.BYTE_ORDER_MARK in res.categories_detected
    assert InvisibleUnicodeCategory.FILLER in res.categories_detected
    assert InvisibleUnicodeCategory.C1_CONTROL in res.categories_detected


def test_bidi_override_protection() -> None:
    """Ensure BiDi overrides (e.g. U+202E RLO) are sanitized to prevent extension spoofing."""
    spoofed_path = "important_document\u202etxt.exe"
    sanitizer = GateGuardDenialSanitizer()
    res = sanitizer.sanitize_path(spoofed_path)

    assert "\u202e" not in res.sanitized_text
    assert InvisibleUnicodeCategory.BIDI_CONTROL in res.categories_detected
    assert res.has_modifications is True


def test_tag_block_ascii_smuggling() -> None:
    """Ensure Unicode tag block characters (U+E0000..U+E007F) used for smuggling are stripped."""
    smuggled_path = "/var/log/app.log\U000e0061\U000e0062\U000e0063"
    sanitizer = GateGuardDenialSanitizer()
    res = sanitizer.sanitize_path(smuggled_path)

    for tag_char in ["\U000e0061", "\U000e0062", "\U000e0063"]:
        assert tag_char not in res.sanitized_text
    assert InvisibleUnicodeCategory.TAG_BLOCK in res.categories_detected
    assert "/var/log/app.log" in res.sanitized_text


def test_variation_selectors_and_fillers() -> None:
    """Ensure variation selectors and Korean/Mongolian fillers are sanitized."""
    text = "file\ufe00name\u180ev1\u115fpart\u2061op.py"
    sanitizer = GateGuardDenialSanitizer()
    res = sanitizer.sanitize_path(text)

    for bad in ["\ufe00", "\u180e", "\u115f", "\u2061"]:
        assert bad not in res.sanitized_text
    assert InvisibleUnicodeCategory.VARIATION_SELECTOR in res.categories_detected
    assert InvisibleUnicodeCategory.FILLER in res.categories_detected
    assert InvisibleUnicodeCategory.INVISIBLE_MATH in res.categories_detected


def test_clean_paths_preserved() -> None:
    """Ensure legitimate paths (Chinese, English, numbers, symbols) are untouched."""
    normal_path = "/Users/workspace/项目代码/src/models/user_account.py"
    sanitizer = GateGuardDenialSanitizer()
    res = sanitizer.sanitize_path(normal_path)

    assert res.sanitized_text == normal_path
    assert res.characters_removed_count == 0
    assert len(res.categories_detected) == 0
    assert res.has_modifications is False
    assert res.was_truncated is False


def test_length_truncation_and_reason_sanitization() -> None:
    """Ensure max_length boundaries and denial reason formatting work correctly."""
    long_path = "a" * 600
    sanitizer = GateGuardDenialSanitizer(DenialSanitizePolicy(max_path_length=200))
    res_path = sanitizer.sanitize_path(long_path)
    assert len(res_path.sanitized_text) == 200
    assert res_path.was_truncated is True

    denial_reason = "Permission denied: access to \u200bsecret token forbidden."
    clean_reason = sanitize_denial_reason(denial_reason)
    assert "\u200b" not in clean_reason
    assert "Permission denied: access to" in clean_reason
    assert "secret token forbidden." in clean_reason


def test_sanitize_denial_payload() -> None:
    """Ensure denial payload dictionary sanitizes tool_name, target_path, and reason."""
    sanitizer = GateGuardDenialSanitizer()
    payload = sanitizer.sanitize_denial_payload(
        tool_name="Edit\u200bFile",
        target_path="/etc/\u200bshadow",
        reason="Blocked write access to \u202epwd.sh file",
    )
    assert "\u200b" not in payload["tool_name"]
    assert "\u200b" not in payload["target_path"]
    assert "\u202e" not in payload["reason"]
    assert payload["tool_name"] == "Edit File"


def test_convenience_helpers_and_classify() -> None:
    """Test top-level convenience functions and codepoint classifications."""
    assert classify_codepoint(0x200B) == InvisibleUnicodeCategory.ZERO_WIDTH
    assert classify_codepoint(0x0041) is None  # 'A' is safe
    assert classify_codepoint(0x001F) == InvisibleUnicodeCategory.ASCII_CONTROL
    assert classify_codepoint(0x0085) == InvisibleUnicodeCategory.C1_CONTROL

    assert sanitize_denial_path("/safe/\u200bfile") == "/safe/ file"
    assert len(detect_categories("")) == 0
