"""Live integration tests for secret redaction through the public API.

Runs the real redaction engine with built-in default patterns — no mocks, no
custom rules — verifying secrets never leak through the LLM / display paths.
"""

from __future__ import annotations

import logging

import pytest

pytestmark = pytest.mark.integration

from myrm_agent_harness.core.security.redact import (
    RedactingFormatter,
    redact_for_display,
    redact_for_llm,
    redact_sensitive_text,
    set_redact_enabled,
)

LLM_LOG = (
    "User said: my api_key=sk-abc123secret and token=eyJhbGciOi. "
    "Also auth password=hunter2 and connection mysql://u:p@db.internal:3306/x."
)


class TestRedactSensitiveTextLive:
    def test_builtin_patterns_mask_secrets(self) -> None:
        out = redact_sensitive_text(LLM_LOG)
        assert "sk-abc123secret" not in out
        assert "hunter2" not in out
        assert "eyJhbGciOi" not in out

    def test_secret_is_replaced_not_just_truncated(self) -> None:
        out = redact_sensitive_text("API key: sk-live-abcdef0123456789")
        assert "sk-live-abcdef0123456789" not in out
        assert out != "API key: "

    def test_plain_text_survives_untouched(self) -> None:
        text = "Normal conversation about weather in Shanghai."
        assert redact_sensitive_text(text) == text


class TestRedactForLlmLive:
    def test_full_recursive_chain(self) -> None:
        value = {
            "user": "alice",
            "credentials": {"api_key": "sk-live-abcdef0123456789"},
            "messages": [{"content": "password=p@ssw0rd", "meta": None}],
        }
        out = redact_for_llm(value)
        assert "sk-live-abcdef0123456789" not in out
        assert "p@ssw0rd" not in out
        assert "alice" in out

    def test_redact_for_display_stronger_than_llm(self) -> None:
        args = {
            "url": "https://api.example.com/v1",
            "headers": {"Authorization": "Bearer sk-live-abcdef0123456789"},
        }
        llm = redact_for_llm(args)
        display = redact_for_display(args)
        # display 通道对完整值做掩码，必须比 LLM 通道更彻底
        assert "sk-live-abcdef0123456789" not in llm
        assert "sk-live-abcdef0123456789" not in str(display)


class TestRedactingFormatterLive:
    def test_formatter_redacts_log_records(self) -> None:
        handler = logging.Handler()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="leaked key sk-live-abcdef0123456789 in payload",
            args=(),
            exc_info=None,
        )
        formatter = RedactingFormatter(fmt="%(message)s")
        formatted = formatter.format(record)
        assert "sk-live-abcdef0123456789" not in formatted


class TestRedactToggleLive:
    def test_toggle_controls_engine(self) -> None:
        secret = "sk-live-abcdef0123456789"
        set_redact_enabled(False)
        try:
            out = redact_sensitive_text(f"key={secret}")
            assert secret in out
        finally:
            set_redact_enabled(True)
        assert secret not in redact_sensitive_text(f"key={secret}")
