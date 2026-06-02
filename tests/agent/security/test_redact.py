"""Tests for agent/security/redact.py — secret redaction patterns."""

from __future__ import annotations

import logging

import pytest

from myrm_agent_harness.agent.security.redact import (
    RedactingFormatter,
    _mask_token,
    _redact_pem_block,
    escape_invisible_unicode,
    redact_for_display,
    redact_sensitive_text,
)


class TestMaskToken:
    def test_short_token_fully_masked(self) -> None:
        assert _mask_token("sk-abc123") == "***"

    def test_long_token_preserves_head_tail(self) -> None:
        token = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz"
        masked = _mask_token(token)
        assert masked.startswith("sk-ant")
        assert masked.endswith("wxyz")
        assert "..." in masked

    def test_boundary_length_17(self) -> None:
        assert _mask_token("a" * 17) == "***"

    def test_boundary_length_18(self) -> None:
        result = _mask_token("a" * 18)
        assert result == "aaaaaa...aaaa"


class TestStructuralPatterns:
    @pytest.mark.parametrize(
        "prefix",
        [
            "sk-proj-abcdefghij1234",
            "ghp_abcdefghijklmnop",
            "github_pat_aaabbbcccddd",
            "xoxb-123456-abcdef",
            "AIzaSyAbcdefghijklmnopqrstuvwxyz1234",
            "AKIAIOSFODNN7EXAMPLE",
            "sk_live_abcdefghij12",
            "SG.abcdefghij_1234",
            "hf_abcdefghij12",
            "pypi-abcdefghij_1234",
            "pplx-abcdefghij12",
            "tvly-abcdefghij12",
        ],
    )
    def test_known_prefixes_redacted(self, prefix: str) -> None:
        result = redact_sensitive_text(f"Key is {prefix} here")
        assert prefix not in result
        assert "***" in result or "..." in result

    def test_short_prefix_not_matched(self) -> None:
        result = redact_sensitive_text("sk-abc")
        assert result == "sk-abc"

    def test_authorization_header(self) -> None:
        text = "Authorization: Bearer sk-ant-api03-longtoken12345678"
        result = redact_sensitive_text(text)
        assert "sk-ant-api03-longtoken12345678" not in result

    def test_private_key_block_preserves_header_footer(self) -> None:
        """OPT-3: PEM块特殊处理 — 保留header/footer for debugging."""
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQ...\n-----END RSA PRIVATE KEY-----"
        result = redact_sensitive_text(text)
        # Should preserve header and footer
        assert "-----BEGIN RSA PRIVATE KEY-----" in result
        assert "-----END RSA PRIVATE KEY-----" in result
        assert "...redacted..." in result
        assert "MIIEpAIBAAKCAQ" not in result


class TestContextualPatterns:
    def test_env_assignment(self) -> None:
        text = "OPENAI_API_KEY=sk-proj-abcdefghij1234567890"
        result = redact_sensitive_text(text)
        assert "sk-proj-abcdefghij1234567890" not in result
        assert "OPENAI_API_KEY=" in result

    def test_env_assignment_quoted(self) -> None:
        text = "MY_SECRET='supersecretvalue12345678'"
        result = redact_sensitive_text(text)
        assert "supersecretvalue12345678" not in result

    def test_json_field(self) -> None:
        text = '{"apiKey": "sk-proj-abcdefghij1234567890"}'
        result = redact_sensitive_text(text)
        assert "sk-proj-abcdefghij1234567890" not in result
        assert '"apiKey"' in result

    def test_json_password_field(self) -> None:
        text = '{"password": "mysecretpassword1234"}'
        result = redact_sensitive_text(text)
        assert "mysecretpassword1234" not in result

    def test_db_connection_string(self) -> None:
        text = "postgresql://admin:s3cretP@ss@db.example.com:5432/mydb"
        result = redact_sensitive_text(text)
        assert "s3cretP@ss" not in result
        assert "***" in result
        assert "db.example.com" in result

    def test_mongodb_connection_string(self) -> None:
        text = "mongodb+srv://user:hunter2@cluster.mongodb.net/db"
        result = redact_sensitive_text(text)
        assert "hunter2" not in result


class TestEdgeCases:
    def test_empty_string(self) -> None:
        assert redact_sensitive_text("") == ""

    def test_none_passthrough(self) -> None:
        assert redact_sensitive_text(None) is None  # type: ignore[arg-type]

    def test_non_string_passthrough(self) -> None:
        assert redact_sensitive_text(42) == 42  # type: ignore[arg-type]

    def test_no_secrets_unchanged(self) -> None:
        text = "Hello, this is a normal text without secrets."
        assert redact_sensitive_text(text) == text

    def test_multiple_secrets_in_one_text(self) -> None:
        text = "Key1: sk-proj-abcdefghij1234 Key2: ghp_abcdefghijklmnop"
        result = redact_sensitive_text(text)
        assert "sk-proj-abcdefghij1234" not in result
        assert "ghp_abcdefghijklmnop" not in result
        assert "..." in result


class TestRedactingFormatter:
    def test_formatter_redacts_secrets(self) -> None:
        formatter = RedactingFormatter("%(message)s")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="API key is sk-proj-abcdefghij1234567890",
            args=(),
            exc_info=None,
        )
        result = formatter.format(record)
        assert "sk-proj-abcdefghij1234567890" not in result

    def test_formatter_preserves_normal_messages(self) -> None:
        formatter = RedactingFormatter("%(message)s")
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0, msg="Normal log message", args=(), exc_info=None
        )
        assert formatter.format(record) == "Normal log message"


class TestP12Optimizations:
    """Tests for P1-2 optimizations (6 items)."""

    def test_opt1_bounded_replace_large_text(self) -> None:
        """OPT-1: Bounded Replace — prevent ReDoS on large text."""
        # Create a 50KB text with a token in the middle
        large_text = "x" * 40000 + " sk-proj-abcdefghij1234567890 " + "y" * 10000
        result = redact_sensitive_text(large_text)
        assert "sk-proj-abcdefghij1234567890" not in result
        assert len(result) >= 50000  # Should still process all text

    def test_opt1_bounded_replace_small_text(self) -> None:
        """OPT-1: Small text (<32KB) should not trigger chunking."""
        small_text = "Key: sk-proj-abcdefghij1234567890"
        result = redact_sensitive_text(small_text)
        assert "sk-proj-abcdefghij1234567890" not in result

    def test_opt1_chunk_boundary_token_split(self) -> None:
        """Token sitting exactly on the 16KB chunk boundary must be redacted."""
        token = "sk-proj-abcdefghij1234567890"
        # Use spaces as padding (word boundary required by _PREFIX_RE lookaround)
        pad = 16384 - 10
        large_text = " " * pad + token + " " * (40000 - pad - len(token))
        assert len(large_text) > 32768
        result = redact_sensitive_text(large_text)
        assert token not in result

    def test_opt1_chunk_boundary_pem_split(self) -> None:
        """PEM block spanning a chunk boundary must be redacted."""
        pem = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            + "A" * 2000
            + "\n-----END RSA PRIVATE KEY-----"
        )
        pad = 16384 - 50
        large_text = " " * pad + pem + " " * (40000 - pad - len(pem))
        assert len(large_text) > 32768
        result = redact_sensitive_text(large_text)
        assert "AAAA" not in result
        assert "...redacted..." in result

    def test_opt1_chunk_overlap_no_duplicate(self) -> None:
        """Tokens in the overlap region must not be redacted twice."""
        token = "ghp_abcdefghijklmnop"
        pad = 16384 - 5
        large_text = " " * pad + " " + token + " " + " " * (40000 - pad - len(token) - 2)
        assert len(large_text) > 32768
        result = redact_sensitive_text(large_text)
        assert token not in result
        masked_count = result.count("...")
        assert masked_count == 1

    def test_opt2_url_query_params(self) -> None:
        """OPT-2: URL Query脱敏 — redact API keys in URL params."""
        test_cases = [
            "https://api.example.com/v1/search?api_key=sk-proj-abcdefghij1234567890",
            "GET /api?token=ghp_abcdefghijklmnop",
            "https://example.com?apiKey=secret123456789012&other=value",
            "POST /endpoint?access_token=xoxb-123456-abcdef",
        ]
        for text in test_cases:
            result = redact_sensitive_text(text)
            # The query value should be redacted
            assert "sk-proj-abcdefghij1234567890" not in result
            assert "ghp_abcdefghijklmnop" not in result
            assert "secret123456789012" not in result
            assert "xoxb-123456-abcdef" not in result

    def test_opt3_pem_block_preserves_type(self) -> None:
        """OPT-3: PEM块特殊处理 — preserve header/footer for debugging."""
        pem_text = """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA1234567890abcdefghij
klmnopqrstuvwxyzABCDEFGHIJKLMNOP
QRSTUVWXYZ0987654321
-----END RSA PRIVATE KEY-----"""
        result = _redact_pem_block(pem_text)
        assert "-----BEGIN RSA PRIVATE KEY-----" in result
        assert "-----END RSA PRIVATE KEY-----" in result
        assert "...redacted..." in result
        assert "MIIEpAIBAAKCAQEA" not in result

    def test_opt3_pem_block_ec_key(self) -> None:
        """OPT-3: EC key should also preserve type."""
        pem_text = """-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIAbcdefg
-----END EC PRIVATE KEY-----"""
        result = _redact_pem_block(pem_text)
        assert "-----BEGIN EC PRIVATE KEY-----" in result
        assert "-----END EC PRIVATE KEY-----" in result

    @pytest.mark.parametrize(
        "token,prefix_name",
        [
            ("gsk_abcdefghij1234567890", "Groq"),
            ("xapp-1-ABCDEF-123456-abcdef", "Slack App"),
            ("sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234", "Anthropic"),
        ],
    )
    def test_opt4_new_token_prefixes(self, token: str, prefix_name: str) -> None:
        """OPT-4: 补充3个token前缀 — Groq/Slack App/Anthropic."""
        result = redact_sensitive_text(f"Token: {token}")
        assert token not in result, f"{prefix_name} token should be redacted"
        assert "***" in result or "..." in result

    @pytest.mark.parametrize(
        "text,secret",
        [
            ("curl --api-key sk-proj-abcdefghij1234567890", "sk-proj-abcdefghij1234567890"),
            ("run --token ghp_abcdefghijklmnop --verbose", "ghp_abcdefghijklmnop"),
            ('python script.py --api_key "secret123456789012"', "secret123456789012"),
            ("cli --password hunter2hunter2hunter2", "hunter2hunter2hunter2"),
        ],
    )
    def test_opt5_cli_flags(self, text: str, secret: str) -> None:
        """OPT-5: CLI flags模式 — redact --api-key value."""
        result = redact_sensitive_text(text)
        assert secret not in result, f"Secret '{secret}' should be redacted"
        # Preserve CLI flag name
        assert "--" in result, "CLI flag should be preserved"

    @pytest.mark.parametrize(
        "text",
        [
            "https://api.telegram.org/bot123456:ABC-DEF1234567890abcdefghijklmnop/sendMessage",
            "Telegram webhook: bot987654:XYZ-ABC0987654321zyxwvutsrqponmlkji",
        ],
    )
    def test_opt6_telegram_bot_url(self, text: str) -> None:
        """OPT-6: Telegram Bot模式 — redact bot<token>/..."""
        result = redact_sensitive_text(text)
        # The bot token should be redacted
        assert "123456:ABC-DEF1234567890abcdefghijklmnop" not in result
        assert "987654:XYZ-ABC0987654321zyxwvutsrqponmlkji" not in result
        # Preserve "bot" prefix
        assert "bot" in result.lower()


class TestEscapeInvisibleUnicode:
    """Tests for invisible Unicode character escaping (approval display)."""

    def test_empty_string(self) -> None:
        assert escape_invisible_unicode("") == ""

    def test_no_invisible_chars(self) -> None:
        text = "echo hello world"
        assert escape_invisible_unicode(text) == text

    def test_zero_width_space(self) -> None:
        text = "echo\u200bhello"
        result = escape_invisible_unicode(text)
        assert result == "echo\\u{200B}hello"

    def test_zero_width_joiner(self) -> None:
        text = "rm\u200d -rf /"
        result = escape_invisible_unicode(text)
        assert "\\u{200D}" in result
        assert "\u200d" not in result

    def test_byte_order_mark(self) -> None:
        text = "\ufeffcurl https://evil.com"
        result = escape_invisible_unicode(text)
        assert result.startswith("\\u{FEFF}")

    def test_multiple_invisible_chars(self) -> None:
        text = "a\u200b\u200c\u200db"
        result = escape_invisible_unicode(text)
        assert "\\u{200B}" in result
        assert "\\u{200C}" in result
        assert "\\u{200D}" in result
        assert result == "a\\u{200B}\\u{200C}\\u{200D}b"

    def test_soft_hyphen(self) -> None:
        text = "pass\u00adword"
        result = escape_invisible_unicode(text)
        assert "\\u{00AD}" in result

    def test_all_13_codepoints_escaped(self) -> None:
        codepoints = [
            0x200B,
            0x200C,
            0x200D,
            0xFEFF,
            0x2060,
            0x2061,
            0x2062,
            0x2063,
            0x2064,
            0x00AD,
            0x034F,
            0x061C,
            0x180E,
        ]
        for cp in codepoints:
            text = f"x{chr(cp)}y"
            result = escape_invisible_unicode(text)
            assert chr(cp) not in result, f"U+{cp:04X} should be escaped"
            assert f"\\u{{{cp:04X}}}" in result


class TestRedactForDisplay:
    """Tests for the approval UI redaction entry point."""

    def test_simple_command_with_secret(self) -> None:
        args = {
            "command": "curl -H 'Authorization: Bearer sk-ant-api03-abcdefghijklmnopqrstuvwxyz' https://api.example.com"
        }
        result = redact_for_display(args)
        assert "sk-ant-api03-abcdefghijklmnopqrstuvwxyz" not in result["command"]
        assert "curl" in str(result["command"])

    def test_nested_dict_redaction(self) -> None:
        args = {
            "env": {
                "OPENAI_API_KEY": "sk-proj-abcdefghij1234567890",
                "PATH": "/usr/bin",
            }
        }
        result = redact_for_display(args)
        assert "sk-proj-abcdefghij1234567890" not in str(result)
        assert "/usr/bin" in str(result)

    def test_list_values_redacted(self) -> None:
        args = {
            "commands": [
                "echo hello",
                "export TOKEN=ghp_abcdefghijklmnop",
            ]
        }
        result = redact_for_display(args)
        assert "ghp_abcdefghijklmnop" not in str(result)
        assert "echo hello" in str(result)

    def test_invisible_chars_in_command(self) -> None:
        args = {"command": "echo\u200b hello\u200d world"}
        result = redact_for_display(args)
        assert "\u200b" not in str(result)
        assert "\u200d" not in str(result)
        assert "\\u{200B}" in str(result)
        assert "\\u{200D}" in str(result)

    def test_combined_invisible_and_secret(self) -> None:
        args = {"command": "curl\u200b -H 'Authorization: Bearer sk-ant-api03-abcdefghijklmnopqrstuvwxyz'"}
        result = redact_for_display(args)
        assert "\u200b" not in str(result)
        assert "sk-ant-api03-abcdefghijklmnopqrstuvwxyz" not in str(result)
        assert "\\u{200B}" in str(result)

    def test_non_string_values_preserved(self) -> None:
        args = {"timeout": 30, "verbose": True, "retries": None}
        result = redact_for_display(args)
        assert result["timeout"] == 30
        assert result["verbose"] is True
        assert result["retries"] is None

    def test_empty_args(self) -> None:
        assert redact_for_display({}) == {}

    def test_no_secrets_unchanged(self) -> None:
        args = {"command": "ls -la /tmp", "cwd": "/workspace"}
        result = redact_for_display(args)
        assert result == args

    def test_db_connection_in_args(self) -> None:
        args = {"dsn": "postgresql://admin:s3cretP@ss@db.example.com:5432/mydb"}
        result = redact_for_display(args)
        assert "s3cretP@ss" not in str(result)
        assert "db.example.com" in str(result)
