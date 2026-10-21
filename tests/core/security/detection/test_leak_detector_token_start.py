"""A vendor prefix marks a key only where a token starts, never at the tail of a word."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.detection.leak_detector import (
    _API_KEY_PATTERNS,
    _NUMBER_LED_KEY_NAMES,
    redact_leaks,
    scan_for_leaks,
)

_OPENAI_BODY = ("aB3dE5fG7h" * 5)[:48]
_OPENAI_KEY = f"sk-{_OPENAI_BODY}"
_PROJECT_KEY = "sk-proj-" + ("aB3-dE5_fG7" * 14)[:150]
_GITHUB_KEY = "ghp_" + "aB3dE5fG7h" * 4
_AWS_KEY = "AKIA" + "ABCD3FGH5JKL7NOP"
_TELEGRAM_KEY = "123456789:" + "aB3dE5fG7h" * 3 + "aB3dE"

# ``sk-`` ends "task", "risk", "disk" and "ask": a hyphenated slug of 48+ characters has the shape of an OpenAI key.
_SLUG_TEXTS = (
    "https://example.com/blog/task-management-best-practices-for-remote-teams-in-2025",
    "disk-encryption-settings-enabled-by-default-in-the-latest-version-of-the-os-release-notes",
    "ask-me-anything-about-the-new-product-roadmap-and-q3-goals-before-friday-afternoon",
    "https://www.nngroup.com/articles/risk-assessment-framework-for-large-language-model-deployments/",
)

# Each key is the only secret in its text; the text around it is how a user pastes one.
_PASTED_KEYS = (
    (_OPENAI_KEY, _OPENAI_KEY),
    (_PROJECT_KEY, _PROJECT_KEY),
    (f"OPENAI_API_KEY={_OPENAI_KEY}", _OPENAI_KEY),
    (f'{{"api_key": "{_OPENAI_KEY}"}}', _OPENAI_KEY),
    (f"Authorization: Bearer {_OPENAI_KEY}", _OPENAI_KEY),
    (f"use '{_OPENAI_KEY}' for the call", _OPENAI_KEY),
    (f"({_OPENAI_KEY})", _OPENAI_KEY),
    (f"my_key_{_OPENAI_KEY}", _OPENAI_KEY),
    (f"我的密钥是{_OPENAI_KEY}，帮我配置", _OPENAI_KEY),
    (f"token {_GITHUB_KEY}", _GITHUB_KEY),
    (f"AWS key {_AWS_KEY}", _AWS_KEY),
    (f"first line\\n{_OPENAI_KEY}\\nlast line", _OPENAI_KEY),
    (f"a\\r\\n{_AWS_KEY}", _AWS_KEY),
    (f"a\\t{_GITHUB_KEY}", _GITHUB_KEY),
    (f"?token%3D{_OPENAI_KEY}", _OPENAI_KEY),
    (f"q%20{_OPENAI_KEY}", _OPENAI_KEY),
    (f"https://api.telegram.org/bot{_TELEGRAM_KEY}/getMe", _TELEGRAM_KEY),
)

# One real key per vendor shape that is not an identifier: the name the table reports for it.
_VENDOR_KEYS = (
    ("openai_key", _OPENAI_KEY),
    ("github_token", _GITHUB_KEY),
    ("aws_access_key", _AWS_KEY),
    ("groq_key", "gsk_" + "aB3dE5fG7h" * 4),
    ("huggingface_token", "hf_" + "aB3dE5fG7h" * 4),
    ("stripe_key", "sk_live_" + "aB3dE5fG7h" * 3),
)


@pytest.mark.parametrize("text", _SLUG_TEXTS)
def test_a_long_slug_is_not_a_key(text: str) -> None:
    assert scan_for_leaks(text) == []
    assert redact_leaks(text) == text


@pytest.mark.parametrize(("text", "key"), _PASTED_KEYS)
def test_a_key_is_masked_wherever_it_is_pasted(text: str, key: str) -> None:
    assert scan_for_leaks(text)
    redacted = redact_leaks(text)
    assert key[6:-4] not in redacted
    assert "[REDACTED:" in redacted


@pytest.mark.parametrize(("name", "key"), _VENDOR_KEYS)
def test_a_vendor_prefix_inside_a_word_is_not_that_vendors_key(name: str, key: str) -> None:
    assert name in scan_for_leaks(key)
    assert name not in scan_for_leaks(f"word{key}")


@pytest.mark.parametrize("text", [f"12{_TELEGRAM_KEY}", f"123{_TELEGRAM_KEY}"])
def test_a_longer_number_in_front_of_a_telegram_id_is_not_a_bot_token(text: str) -> None:
    assert "telegram_bot" not in scan_for_leaks(text)
    assert "telegram_bot" in scan_for_leaks(f"bot{_TELEGRAM_KEY}")


def test_the_shapes_opening_with_digits_are_the_ones_named_for_the_number_start() -> None:
    opening_with_digits = {name for name, pattern in _API_KEY_PATTERNS if pattern.pattern.startswith("\\d")}

    assert opening_with_digits == _NUMBER_LED_KEY_NAMES
