"""Tests for labeled secret spans and position-based redaction."""

from __future__ import annotations

import time

import pytest

from myrm_agent_harness.core.security.persistence.secret_spans import (
    REDACTION_MARKER,
    find_assignment_secret_spans,
    redact_spans,
)


def _secrets(text: str) -> list[str]:
    return [text[start:end] for start, end in find_assignment_secret_spans(text)]


class TestRedactSpans:
    def test_replaces_only_the_spans(self) -> None:
        text = "a secret1 b secret1 c"

        assert redact_spans(text, [(2, 9)]) == f"a {REDACTION_MARKER} b secret1 c"

    def test_overlapping_and_adjacent_spans_collapse_into_one_marker(self) -> None:
        assert redact_spans("0123456789", [(2, 5), (4, 7), (7, 9)]) == f"01{REDACTION_MARKER}9"

    def test_unordered_spans_and_no_spans(self) -> None:
        assert redact_spans("abcdef", [(4, 5), (0, 1)]) == f"{REDACTION_MARKER}bcd{REDACTION_MARKER}f"
        assert redact_spans("abcdef", []) == "abcdef"


class TestFindAssignmentSecretSpans:
    def test_offsets_are_relative_to_the_whole_text_across_line_endings(self) -> None:
        text = "user: bob\r\npassword: dragonfly\nDB_PASSWORD=Zk9#mango42\n"

        assert _secrets(text) == ["dragonfly", "Zk9#mango42"]

    def test_quoted_value_extends_to_the_closing_quote(self) -> None:
        assert _secrets('passphrase: "correct horse battery staple" # note') == ["correct horse battery staple"]

    def test_value_stops_at_the_first_non_ascii_character(self) -> None:
        assert _secrets("密码：abc123456，请勿转发。") == ["abc123456"]

    def test_markdown_emphasis_around_a_value_is_not_part_of_the_secret(self) -> None:
        assert _secrets("- password: **hunter2hunter2**") == ["hunter2hunter2"]
        assert _secrets("token: **word**") == []

    def test_token_label_naming_a_usage_unit_is_not_a_secret(self) -> None:
        assert _secrets("Token：180k-280k（因为要多次迭代）") == []
        assert _secrets("[模型 Token: DeepSeek-V3 1251K Tokens]") == []
        assert _secrets("token = abcd1234efgh5678") == ["abcd1234efgh5678"]

    def test_letters_only_value_needs_a_password_key(self) -> None:
        assert _secrets("password: dragonfly") == ["dragonfly"]
        assert _secrets("secret: Employees only") == []
        assert _secrets("api_key: abcdefghijklmnop") == []

    @pytest.mark.parametrize(
        "text",
        [
            "password = settings.DB_PASSWORD",
            "password: [REDACTED]",
            "api_key: [REDACTED:openai_api_key]",
            "password: ${DB_PASSWORD}",
            "def login(password: Optional[str] = None)",
            "password: $DB_PASSWORD",
            "token: {token_efficiency:.2f}",
            "Client(host=host, password=password, passphrase=passphrase)",
            "{ current_password: currentPassword, new_password: newPassword }",
            "token = _active_value(settings, name)",
            "secret = _resolve_secret(ctx)",
            "raise Error(code=status.HTTP_400_BAD_REQUEST, password=a-zA-Z0-9_)",
        ],
        ids=[
            "attribute",
            "marker",
            "vendor-marker",
            "template",
            "annotation",
            "shell-variable",
            "format-field",
            "pass-through-argument",
            "camel-case-field",
            "private-call",
            "private-call-secret",
            "character-class",
        ],
    )
    def test_references_and_markers_are_not_secrets(self, text: str) -> None:
        assert _secrets(text) == []

    @pytest.mark.parametrize(
        ("text", "secret"),
        [
            ('export DB_PASSWORD="Pa$$w0rd2024"', "Pa$$w0rd2024"),
            ('db_password: "Zk9%mango42"', "Zk9%mango42"),
            ("api_key=ab$cdef1234567", "ab$cdef1234567"),
            ("secret: Zk9$mango42xyz", "Zk9$mango42xyz"),
            ("PASSWORD=Zk9%mango42", "Zk9%mango42"),
        ],
        ids=["dollar-in-env-export", "percent-in-yaml", "dollar-in-api-key", "dollar-in-secret", "percent-in-env"],
    )
    def test_dollar_and_percent_inside_a_value_are_redacted(self, text: str, secret: str) -> None:
        assert _secrets(text) == [secret]

    def test_long_unbroken_line_is_scanned_in_linear_time(self) -> None:
        started = time.perf_counter()
        find_assignment_secret_spans("ab_" * 20_000)

        assert time.perf_counter() - started < 2.0
