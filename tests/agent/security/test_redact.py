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

    def test_authorization_basic_header(self) -> None:
        """Basic 头（base64 user:pass）凭据必须被掩码，scheme 词保留。"""
        base64_cred = "QWxhZGRpbjpvcGVuc2VzYW1l"  # "Aladdin:open sesame"
        text = f"Authorization: Basic {base64_cred}"
        result = redact_sensitive_text(text)
        assert base64_cred not in result
        assert "Authorization: Basic" in result

    def test_authorization_digest_header(self) -> None:
        text = "Authorization: Digest username=Mufasa, realm=test, nonce=abc123"
        result = redact_sensitive_text(text)
        # scheme 词保留，credential 段（首个 key=value）被掩码（与 Hermes 行为一致）
        assert "Authorization: Digest" in result
        assert "Mufasa" not in result

    def test_authorization_header_quote_not_absorbed(self) -> None:
        """credential 紧贴闭引号时，引号不能被吸入匹配导致语法破坏。"""
        text = 'curl -H "Authorization: Bearer sk-ant-api03-longtoken12345678"'
        result = redact_sensitive_text(text)
        assert "sk-ant-api03-longtoken12345678" not in result
        assert result.count('"') == 2

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

    def test_env_quoted_with_spaces_no_partial_leak(self) -> None:
        """引号值含空格时整体脱敏，杜绝 `password="my` 部分匹配泄漏尾部。"""
        text = 'password="my secret pass"'
        result = redact_sensitive_text(text)
        assert "my secret pass" not in result
        assert 'password="***"' in result

    def test_env_getenv_quoted_value_kept(self) -> None:
        """引号包裹的 `os.getenv(...)` 仍是变量名引用，不得掩码。"""
        text = "OPENAI_API_KEY=os.getenv(\"X\")"
        assert redact_sensitive_text(text) == text

    def test_json_field(self) -> None:
        text = '{"apiKey": "sk-proj-abcdefghij1234567890"}'
        result = redact_sensitive_text(text)
        assert "sk-proj-abcdefghij1234567890" not in result
        assert '"apiKey"' in result

    def test_json_password_field(self) -> None:
        text = '{"password": "mysecretpassword1234"}'
        result = redact_sensitive_text(text)
        assert "mysecretpassword1234" not in result

    def test_json_escaped_quote_no_partial_leak(self) -> None:
        """JSON 单反斜杠转义引号（`\"`）不得截断泄漏尾部明文。"""
        text = r'{"password": "my\"secret\"123"}'
        result = redact_sensitive_text(text)
        assert '"***"' in result
        assert "secret" not in result

    def test_env_escaped_quote_no_partial_leak(self) -> None:
        """ENV 引号值含单反斜杠转义（`KEY="my\"secret"`）整体脱敏。"""
        text = r'API_KEY="my\"secret\"123"'
        result = redact_sensitive_text(text)
        assert 'API_KEY="***"' in result
        assert "secret" not in result

    def test_env_single_quote_escaped_no_leak(self) -> None:
        """ENV 单引号值含 `\'` 转义（`KEY='my\'secret'`）整体脱敏。"""
        text = r"API_KEY='my\'secret\'123'"
        result = redact_sensitive_text(text)
        assert "API_KEY='***'" in result
        assert "secret" not in result

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


class TestRedactEngineHardening:
    """#170 引擎加固：URL 吞参 / key 名误伤 / 控制字符 / userinfo / header / JWT / lookup."""

    def test_url_query_preserves_following_params(self) -> None:
        """ENV 正则不得吞掉 URL query 中 `&` 分隔的后续参数。"""
        text = "https://api.example.com/v1/data?token=sk-live-abcdefghijklmnopqrst&limit=50&page=2"
        result = redact_sensitive_text(text)
        assert "sk-live-abcdefghijklmnopqrst" not in result
        assert "&limit=50&page=2" in result

    def test_url_query_env_names_fully_covered(self) -> None:
        """URL 参数 key 名单必须覆盖全部 ENV key——`?credential=`/`?auth=`/`?passwd=`
        不得因 ENV 正则的负向后顾而双双落空明文泄漏。"""
        for key in ("credential", "auth", "passwd"):
            text = f"https://x.com/?{key}=mysecretvalue12345678&page=2"
            result = redact_sensitive_text(text)
            assert "mysecretvalue12345678" not in result, f"{key} 泄漏"
            assert "&page=2" in result, f"{key} 吞参"

    def test_cli_flag_name_not_corrupted(self) -> None:
        """短 value（`s`）不得误伤 flag 名（`--secret` → `--***ecret`）。"""
        result = redact_sensitive_text("curl --secret s https://x.com")
        assert "--secret ***" in result

    def test_cli_quoted_with_spaces_no_partial_leak(self) -> None:
        """`--password "my secret pass"` 引号值含空格整体脱敏。"""
        result = redact_sensitive_text('--password "my secret pass"')
        assert "my secret pass" not in result
        assert '--password "***"' in result

    def test_cli_escaped_quote_no_partial_leak(self) -> None:
        """CLI 引号值含单反斜杠转义（`--password "my\\"secret"`）整体脱敏。"""
        result = redact_sensitive_text(r'--password "my\"secret\"123"')
        assert "secret" not in result
        assert '--password "***"' in result

    def test_url_query_key_name_not_corrupted(self) -> None:
        """value 是 key 名子串时 key 名不得被连带破坏。"""
        result = redact_sensitive_text("https://api.example.com?api_key=a&limit=10")
        assert "api_key=***" in result
        assert "&limit=10" in result

    def test_control_char_split_token_redacted(self) -> None:
        """ESC 控制字符拆分的 token 必须被掩码（对齐 Hermes #77484）。"""
        token = "sk-abc\x1bdefghijklmnopqrstuvwxyz123"
        result = redact_sensitive_text(f"Token: {token}")
        assert token not in result
        assert "***" in result or "..." in result

    def test_zero_width_split_token_redacted(self) -> None:
        """零宽空格拆分的 token 必须被掩码。"""
        token = "ghp_\u200babcdefghijklmnop"
        result = redact_sensitive_text(token)
        assert "abcdefghijklmnop" not in result

    def test_control_split_does_not_cross_line(self) -> None:
        """跨行场景不得把下一行普通文本一起掩码（`ghp_<token>\\nbutton`）。"""
        text = "ghp_abcdefghijklmnop\nbutton [ref=e3]"
        result = redact_sensitive_text(text)
        assert "button [ref=e3]" in result

    def test_url_userinfo_password_redacted(self) -> None:
        """`scheme://user:pass@host` 的密码段掩码、用户名保留。"""
        text = "https://user:token123@api.example.com/v1/foo"
        result = redact_sensitive_text(text)
        assert "token123" not in result
        assert "user:***@" in result

    def test_url_bare_token_redacted(self) -> None:
        """`scheme://TOKEN@host` 无冒号 bare-token 掩码（git 私有仓库 URL）。"""
        text = "git clone https://mysecretvalue12345678@github.com/org/repo.git"
        result = redact_sensitive_text(text)
        assert "mysecretvalue12345678" not in result

    def test_secret_header_redacted(self) -> None:
        """x-api-key 等认证头值必须掩码。"""
        text = "x-api-key: my-custom-secret-value-12345"
        result = redact_sensitive_text(text)
        assert "my-custom-secret-value-12345" not in result
        assert "x-api-key:" in result

    def test_bare_jwt_redacted(self) -> None:
        """无 key 上下文的裸 JWT 必须掩码（对齐 Hermes _JWT_RE）。"""
        jwt = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
            "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        )
        result = redact_sensitive_text(f"id token: {jwt}")
        assert jwt not in result

    def test_env_lookup_value_preserved(self) -> None:
        """`os.getenv('X')` 是变量名引用，不得掩码破坏代码示例。"""
        text = "OPENAI_API_KEY=os.getenv('OPENAI_API_KEY')"
        result = redact_sensitive_text(text)
        assert "os.getenv('OPENAI_API_KEY')" in result

    def test_oauth_code_not_redacted(self) -> None:
        """OAuth 授权码（`?code=`）不属于凭据名单，保持放行（对齐 Hermes 全局策略）。"""
        text = "https://login.example.com/callback?code=abc123&state=xyz&scope=read"
        result = redact_sensitive_text(text)
        assert "code=abc123" in result

    def test_short_username_not_bare_token(self) -> None:
        """短用户名（<8 字符）不得被 bare-token 误伤。"""
        text = "https://user@example.com"
        result = redact_sensitive_text(text)
        assert "user@example.com" in result


class TestRedactYamlColon:
    """#170 YAML/冒号式配置脱敏——`password: secret` 不再明文泄漏。"""

    def test_yaml_indented_password(self) -> None:
        text = "  password: mysecretvalue12345678"
        result = redact_sensitive_text(text)
        assert "mysecretvalue12345678" not in result
        assert "password:" in result

    def test_yaml_line_start_password(self) -> None:
        text = "password: mysecretvalue12345678"
        result = redact_sensitive_text(text)
        assert "mysecretvalue12345678" not in result

    def test_yaml_dotted_config_key(self) -> None:
        text = "spring.datasource.password: hunter2"
        result = redact_sensitive_text(text)
        assert "hunter2" not in result
        assert "spring.datasource.password:" in result

    def test_yaml_quoted_value(self) -> None:
        """`password: "hunter2!"` 引号值必须脱敏且保留引号结构。"""
        text = '  password: "hunter2!"'
        result = redact_sensitive_text(text)
        assert "hunter2!" not in result
        assert 'password: "***"' in result

    def test_yaml_space_before_colon(self) -> None:
        """`password : secret`（冒号前空格）是合法 YAML，必须脱敏。"""
        text = "password : hunter2"
        result = redact_sensitive_text(text)
        assert "hunter2" not in result
        assert "password : ***" in result

    def test_yaml_spaces_both_sides(self) -> None:
        """`api_key  :  sk-test...` 冒号两侧多空格均脱敏。"""
        text = "api_key  :  sk-test123456789012345"
        result = redact_sensitive_text(text)
        assert "sk-test123456789012345" not in result
        assert "sk-test123456789012345"[:6] not in result

    def test_yaml_quoted_with_spaces_no_partial_leak(self) -> None:
        """`password: "my secret pass"` 引号值含空格整体脱敏。"""
        text = 'password: "my secret pass"'
        result = redact_sensitive_text(text)
        assert "my secret pass" not in result
        assert 'password: "***"' in result

    def test_yaml_escaped_quote_no_partial_leak(self) -> None:
        """YAML 引号值含单反斜杠转义（`password: "my\\"secret"`）整体脱敏。"""
        result = redact_sensitive_text(r'password: "my\"secret\"123"')
        assert "secret" not in result
        assert 'password: "***"' in result

    def test_yaml_single_quote_doubled_escape_no_leak(self) -> None:
        """YAML 单引号字符串 `''` 转义（`password: 'it''s'`）整体脱敏。"""
        result = redact_sensitive_text("password: 'it''s a secret'")
        assert "secret" not in result
        assert "password: '***'" in result

    def test_yaml_single_quote_doubled_escape_multi(self) -> None:
        """多段 `''` 转义单引号值（`token: 'x''y''z'`）整体脱敏。"""
        result = redact_sensitive_text("token: 'x''y''z'")
        assert "y" not in result
        assert "token: '***'" in result

    def test_yaml_keyword_in_value_not_redacted(self) -> None:
        """关键词在 value（`note: secret meeting`）不得误伤。"""
        text = "note: secret meeting"
        assert redact_sensitive_text(text) == text

    def test_yaml_author_prose_not_redacted(self) -> None:
        """`author: John Smith` 是散文，不得被 YAML 正则误伤。"""
        text = "author: John Smith"
        assert redact_sensitive_text(text) == text

    def test_yaml_secretary_prose_not_redacted(self) -> None:
        """`Secretary: J.Smith` 内嵌 secret 关键词但非词边界，不得误伤。"""
        text = "Secretary: J.Smith"
        assert redact_sensitive_text(text) == text

    def test_yaml_url_skipped(self) -> None:
        """含 `://` 的 URL 文本不触发 YAML 正则（防 URL query 误伤）。"""
        text = "https://example.com:8080/path?mode=prod"
        assert redact_sensitive_text(text) == text

    def test_yaml_env_lookup_value_preserved(self) -> None:
        """`api_key: os.getenv('X')` 是变量名引用，不得掩码破坏代码示例。"""
        text = "api_key: os.getenv('API_KEY')"
        result = redact_sensitive_text(text)
        assert "os.getenv('API_KEY')" in result


class TestRedactLowerEnv:
    """#170 小写/短名 env 脱敏——`db_pw=`/`openai_key=` 不再明文泄漏。"""

    def test_short_env_name_db_pw(self) -> None:
        text = "DB_PW=mysecretvalue12345678"
        result = redact_sensitive_text(text)
        assert "mysecretvalue12345678" not in result
        assert "DB_PW=" in result

    def test_lowercase_env_openai_key(self) -> None:
        text = "openai_key=mysecretvalue12345678"
        result = redact_sensitive_text(text)
        assert "mysecretvalue12345678" not in result
        assert "openai_key=" in result

    def test_lowercase_env_fal_key(self) -> None:
        text = "FAL_KEY=mysecretvalue12345678"
        result = redact_sensitive_text(text)
        assert "mysecretvalue12345678" not in result

    def test_bare_password_eq_still_redacted(self) -> None:
        """裸 `password=xxx`（无下划线）由大写 ENV 正则 IGNORECASE 覆盖。"""
        text = "password=mysecretvalue12345678"
        result = redact_sensitive_text(text)
        assert "mysecretvalue12345678" not in result

    def test_lower_env_url_query_short_key(self) -> None:
        """URL query 中的小写短名（`?openai_key=`）由 _URL_QUERY_RE 覆盖脱敏。"""
        text = "https://x.com/?openai_key=mysecretvalue12345678&page=2"
        result = redact_sensitive_text(text)
        assert "mysecretvalue12345678" not in result
        assert "&page=2" in result


class TestRedactFormBody:
    """#170 form-urlencoded body 逐对脱敏——杜绝 `\\S+` 吞参与前缀泄漏。"""

    def test_form_body_token_fully_redacted(self) -> None:
        text = "token=abc&limit=50&page=2"
        result = redact_sensitive_text(text)
        assert result == "token=***&limit=50&page=2"

    def test_form_body_middle_token(self) -> None:
        text = "a=1&token=abc&limit=50"
        result = redact_sensitive_text(text)
        assert result == "a=1&token=***&limit=50"

    def test_form_body_no_sensitive_key_unchanged(self) -> None:
        text = "user=alice&limit=50&page=2"
        assert redact_sensitive_text(text) == text

    def test_form_body_short_env_not_swallowed(self) -> None:
        """大写在 `&` 处截断，不吞后续参数。"""
        text = "OPENAI_API_KEY=sk-proj-abc&other=1"
        result = redact_sensitive_text(text)
        assert result == "OPENAI_API_KEY=***&other=1"

    def test_form_body_with_newline_not_triggered(self) -> None:
        """含换行的文本不是纯 form body，放行给其他正则处理。"""
        text = "token=abc\n&limit=50"
        result = redact_sensitive_text(text)
        assert "abc" not in result

    def test_form_body_preserves_leading_trailing_whitespace(self) -> None:
        """首尾空白保持原样（重建仅作用于 strip 后的 body）。"""
        text = "  token=abc&page=1  "
        result = redact_sensitive_text(text)
        assert result == "  token=***&page=1  "


class TestRedactProseWordBoundary:
    """#170 词边界校验——`author=`/`tokenizer=` 等散文词不再被 ENV 正则误伤。"""

    def test_prose_author_not_redacted(self) -> None:
        text = "author=John Smith"
        assert redact_sensitive_text(text) == text

    def test_prose_tokenizer_not_redacted(self) -> None:
        text = "tokenizer=cl100k_base"
        assert redact_sensitive_text(text) == text

    def test_prose_secretary_not_redacted(self) -> None:
        text = "secretary=John Smith"
        assert redact_sensitive_text(text) == text

    def test_all_caps_underscore_token_still_redacted(self) -> None:
        """下划线分隔的 ALL-CAPS key（`MY_TOKEN=`）词边界命中，仍然脱敏。"""
        text = "MY_TOKEN=mysecretvalue12345678"
        result = redact_sensitive_text(text)
        assert "mysecretvalue12345678" not in result

    def test_embedded_all_caps_token_not_redacted(self) -> None:
        """`MYTOKEN=`（无分隔内嵌）词边界不命中，保持原样（对齐 Hermes）。"""
        text = "MYTOKEN=mysecretvalue12345678"
        assert redact_sensitive_text(text) == text

    def test_underscore_boundary_keyword_still_redacted(self) -> None:
        """下划线分隔的 key（`MY_ACCESS_TOKEN=`）词边界命中，仍然脱敏。"""
        text = "MY_ACCESS_TOKEN=mysecretvalue12345678"
        result = redact_sensitive_text(text)
        assert "mysecretvalue12345678" not in result
