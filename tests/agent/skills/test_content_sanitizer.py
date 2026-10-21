"""Tests for the skill export content sanitizer.

Covers all pattern categories, edge cases, and the ignored_indices mechanism.
"""

from typing import get_args

import pytest

from myrm_agent_harness.agent.skills.security import (
    ContentSanitizer,
    SanitizationResult,
    content_sanitizer,
)
from myrm_agent_harness.agent.skills.security.content_sanitizer import _SECRET_RULES, SecretKind, _merge_overlaps


class TestModuleExports:
    """Verify public API surface."""

    def test_singleton_instance(self):
        assert isinstance(content_sanitizer, ContentSanitizer)

    def test_sanitize_returns_result(self):
        result = content_sanitizer.sanitize("hello", "test.md")
        assert isinstance(result, SanitizationResult)

    def test_redaction_type(self):
        result = content_sanitizer.sanitize("token = ghp_XxxYyyZzz1234567890abcdef12345678", "test.py")
        assert len(result.redactions) == 1
        r = result.redactions[0]
        assert "line_number" in r
        assert "original" in r
        assert "redacted" in r
        assert r["kinds"] == ["api_token"]
        assert "reason" not in r


class TestTokenPrefixDetection:
    """Detect known API key prefix formats."""

    @pytest.mark.parametrize(
        "token",
        [
            "ghp_XxxYyyZzz1234567890abcdef12345678",
            "sk_live_51HGV8qKXoK4sR3B",
            "sk_test_51HGV8qKXoK4sR3B",
            "AKIAIOSFODNN7EXAMPLE",
            "SG.XxxYyyZzz1234567890",
            "hf_OgXxxYyyZzz1234567890",
            "xoxb-123456789012-1234567890123-xxxyyy",
            "r8_XxxYyyZzz1234567890",
        ],
    )
    def test_detects_token_prefixes(self, token):
        result = content_sanitizer.sanitize(f"key = {token}", "test.py")
        assert not result.is_safe
        assert "REDACTED" in result.sanitized_content


class TestEnvironmentVariables:
    """Detect env var assignments with secret-like names."""

    def test_env_export(self):
        result = content_sanitizer.sanitize('export OPENAI_API_KEY="sk-proj-xxxyyyzzz"', "test.sh")
        assert not result.is_safe
        assert "REDACTED" in result.sanitized_content

    def test_env_inline(self):
        result = content_sanitizer.sanitize("API_KEY=my-secret-value-12345", ".env")
        assert not result.is_safe


class TestJsonFields:
    """Detect JSON secret fields."""

    def test_json_api_key(self):
        result = content_sanitizer.sanitize('"api_key": "my-secret-value-12345"', "config.json")
        assert not result.is_safe
        assert "REDACTED" in result.sanitized_content

    def test_json_token(self):
        result = content_sanitizer.sanitize('"token": "abc123def456"', "config.json")
        assert not result.is_safe


class TestDatabaseConnections:
    """Detect database connection string passwords."""

    def test_postgres(self):
        result = content_sanitizer.sanitize("postgres://admin:s3cr3t@db.example.com:5432/prod", "config.yaml")
        assert not result.is_safe
        assert "***" in result.sanitized_content

    def test_mongodb(self):
        result = content_sanitizer.sanitize("mongodb+srv://user:password123@cluster.mongodb.net/db", "config.yaml")
        assert not result.is_safe


class TestUrlParameters:
    """Detect sensitive URL query parameters."""

    def test_api_key_param(self):
        result = content_sanitizer.sanitize("https://api.example.com?api_key=sk_test_xxxyyy", "test.md")
        assert not result.is_safe

    def test_token_param(self):
        result = content_sanitizer.sanitize("https://example.com/cb?token=abc123&state=xyz", "test.md")
        assert not result.is_safe


class TestCliFlags:
    """Detect CLI flags with secrets."""

    def test_api_key_flag(self):
        result = content_sanitizer.sanitize("--api-key sk_test_1234567890", "test.sh")
        assert not result.is_safe

    def test_token_flag(self):
        result = content_sanitizer.sanitize("--token my_secret_token_value", "test.sh")
        assert not result.is_safe


class TestTelegramBotTokens:
    """Detect Telegram bot tokens."""

    def test_bot_token(self):
        result = content_sanitizer.sanitize("bot123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw", "test.md")
        assert not result.is_safe


class TestAuthorizationHeaders:
    """Detect Authorization: Bearer headers."""

    def test_bearer_jwt(self):
        result = content_sanitizer.sanitize(
            "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc",
            "test.md",
        )
        assert not result.is_safe
        assert "REDACTED" in result.sanitized_content

    def test_bearer_lowercase(self):
        result = content_sanitizer.sanitize(
            "authorization: bearer my-long-token-value-here",
            "test.md",
        )
        assert not result.is_safe


class TestPrivateKeys:
    """Detect PEM private key blocks."""

    def test_rsa_key(self):
        pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA0Z3VS5JJcds3xfn\n-----END RSA PRIVATE KEY-----"
        result = content_sanitizer.sanitize(pem, "key.pem")
        assert not result.is_safe
        assert "...redacted..." in result.sanitized_content

    def test_preserves_pem_markers(self):
        pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA0Z3VS5JJcds3xfn\n-----END RSA PRIVATE KEY-----"
        result = content_sanitizer.sanitize(pem, "key.pem")
        assert "-----BEGIN RSA PRIVATE KEY-----" in result.sanitized_content
        assert "-----END RSA PRIVATE KEY-----" in result.sanitized_content


class TestAbsolutePaths:
    """Detect absolute paths (macOS, Linux, Windows)."""

    def test_macos_path_line_start(self):
        result = content_sanitizer.sanitize("/Users/alice/projects/my-api/config.json", "test.md")
        assert not result.is_safe
        assert "REDACTED_PATH" in result.sanitized_content

    def test_linux_path_line_start(self):
        result = content_sanitizer.sanitize("/home/admin/secrets/api.key", "test.md")
        assert not result.is_safe

    def test_windows_path_line_start(self):
        result = content_sanitizer.sanitize("C:\\Users\\John\\Documents\\secrets.txt", "test.md")
        assert not result.is_safe

    def test_macos_path_after_space(self):
        result = content_sanitizer.sanitize("cd /Users/alice/projects", "test.sh")
        assert not result.is_safe

    def test_macos_path_after_equals(self):
        result = content_sanitizer.sanitize("path=/Users/alice/config", "test.env")
        assert not result.is_safe

    def test_system_path_not_detected(self):
        result = content_sanitizer.sanitize("/System/Library/Frameworks/CoreFoundation.framework", "test.md")
        assert result.is_safe

    def test_usr_local_not_detected(self):
        result = content_sanitizer.sanitize("/usr/local/bin/python3", "test.md")
        assert result.is_safe


class TestSafeContent:
    """Ensure no false positives on safe content."""

    def test_normal_text(self):
        result = content_sanitizer.sanitize("Hello world, this is normal text", "test.md")
        assert result.is_safe

    def test_empty_string(self):
        result = content_sanitizer.sanitize("", "empty.md")
        assert result.is_safe

    def test_code_without_secrets(self):
        result = content_sanitizer.sanitize("def hello():\n    return 'world'", "test.py")
        assert result.is_safe


class TestIgnoredIndices:
    """Test user-toggle mechanism for selectively ignoring redactions."""

    def test_ignore_first_redaction(self):
        content = "/Users/alice/secret\nAuthorization: Bearer mytoken123"
        result = content_sanitizer.sanitize(content, "test.md", ignored_indices=[0])
        assert len(result.redactions) == 1
        assert result.redactions[0]["kinds"] == ["authorization_header"]

    def test_ignore_all(self):
        content = "key = ghp_XxxYyyZzz1234567890abcdef12345678"
        result = content_sanitizer.sanitize(content, "test.py", ignored_indices=[0])
        assert len(result.redactions) == 0
        assert result.is_safe


class TestRedactedFileKeepsItsShape:
    """Redaction replaces the secret and nothing else around it."""

    def test_final_line_break_survives(self):
        content = "export GITHUB_TOKEN=ghp_XxxYyyZzz1234567890abcdef12345678\necho done\n"
        result = content_sanitizer.sanitize(content, "run.sh")
        assert not result.is_safe
        assert result.sanitized_content.startswith("export GITHUB_TOKEN=<REDACTED")
        assert result.sanitized_content.endswith("\necho done\n")

    def test_missing_final_line_break_is_not_invented(self):
        content = "echo start\nexport GITHUB_TOKEN=ghp_XxxYyyZzz1234567890abcdef12345678"
        result = content_sanitizer.sanitize(content, "run.sh")
        assert not result.is_safe
        assert not result.sanitized_content.endswith("\n")


class TestBytesInput:
    """Test bytes input handling."""

    def test_utf8_bytes(self):
        content = b"key = ghp_XxxYyyZzz1234567890abcdef12345678"
        result = content_sanitizer.sanitize(content, "test.py")
        assert not result.is_safe

    def test_invalid_utf8(self):
        content = b"\x80\x81\x82"
        result = content_sanitizer.sanitize(content, "binary.bin")
        assert result.is_safe


class TestMultipleSecretsPerLine:
    """Test handling of multiple secrets on a single line."""

    def test_path_and_token(self):
        content = "/Users/alice/path ghp_XxxYyyZzz1234567890abcdef12345678"
        result = content_sanitizer.sanitize(content, "test.md")
        assert not result.is_safe
        assert len(result.redactions) == 1
        assert "REDACTED" in result.sanitized_content


_SECRET_LINES = [
    ("API_KEY=abc123def456ghi789", "abc123def456ghi789"),
    ('export SECRET_TOKEN="abc123def456ghi789"', "abc123def456ghi789"),
    ("OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz0123456789", "abcdefghijklmnopqrstuvwxyz0123456789"),
    ("db_pw=hunter2hunter2", "hunter2hunter2"),
    ("password: hunter2hunter2", "hunter2hunter2"),
    ('{"password": "hunter2hunter2"}', "hunter2hunter2"),
    ("curl https://x.io/a?api_key=abc123def456ghi789&b=1", "abc123def456ghi789"),
    ("https://user:hunter2pass@example.com/x", "hunter2pass"),
    ("git clone https://ghtokenvalue12345@example.com/r.git", "ghtokenvalue12345"),
    ("postgres://admin:s3cr3tpass@db.example.com/prod", "s3cr3tpass"),
    (
        "https://api.telegram.org/bot123456789:ABCdefGhIJKlmNoPQRsTUVwxyz0123456789/send",
        "ABCdefGhIJKlmNoPQRsTUVwxyz0123456789",
    ),
    ("Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123456789", "abcdefghijklmnopqrstuvwxyz0123456789"),
    ("Authorization: Basic dXNlcjpwYXNzd29yZA==", "dXNlcjpwYXNzd29yZA=="),
    ("Authorization: abcdefghijklmnop12345", "abcdefghijklmnop12345"),
    ("curl -H 'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abcdefghijklmnopqrstuvwxyz'", "abcdefghijklmnopqrstuvwxyz"),
    ("password: 123456", "123456"),
    ("x-api-key: abc123def456ghi789", "abc123def456ghi789"),
    ("mycli --api-key abc123def456ghi789", "abc123def456ghi789"),
    ("token = ghp_XxxYyyZzz1234567890abcdef12345678", "XxxYyyZzz1234567890abcdef12345678"),
    ("echo eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sigsigsig", "eyJzdWIiOiIxIn0"),
]


class TestSecretNeverSurvives:
    """The secret itself must be gone from the output and from the preview diff."""

    @pytest.mark.parametrize(("line", "secret"), _SECRET_LINES)
    def test_secret_is_removed(self, line, secret):
        result = content_sanitizer.sanitize(line, "test.md")
        assert not result.is_safe
        assert secret not in result.sanitized_content
        assert all(secret not in r["redacted"] for r in result.redactions)

    @pytest.mark.parametrize(("line", "secret"), _SECRET_LINES)
    def test_replacement_markers_never_nest(self, line, secret):
        redacted = content_sanitizer.sanitize(line, "test.md").sanitized_content
        assert "<REDACTED_TOKEN<" not in redacted
        assert "<REDACTED_VALUE<" not in redacted


class TestSurroundingSyntaxIsPreserved:
    """Only the secret is replaced; keys, quotes, flags and URL structure stay."""

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("API_KEY=abc123def456ghi789", "API_KEY=<REDACTED_VALUE>"),
            ('export SECRET_TOKEN="abc123def456ghi789"', 'export SECRET_TOKEN="<REDACTED_VALUE>"'),
            ("OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz0123456789", "OPENAI_API_KEY=<REDACTED_TOKEN>"),
            ("curl https://x.io/a?api_key=abc123def456ghi789&b=1", "curl https://x.io/a?api_key=<REDACTED_PARAM>&b=1"),
            ("Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123456789", "Authorization: Bearer <REDACTED_TOKEN>"),
            ("Authorization: abcdefghijklmnop12345", "Authorization: <REDACTED_TOKEN>"),
            ("mycli --api-key abc123def456ghi789", "mycli --api-key <REDACTED_VALUE>"),
            ("https://user:hunter2pass@example.com/x", "https://user:***@example.com/x"),
        ],
    )
    def test_only_the_secret_is_replaced(self, line, expected):
        assert content_sanitizer.sanitize(line, "test.md").sanitized_content == expected


class TestProseIsNotRedacted:
    """Names that merely contain a keyword, and variable lookups, are not credentials."""

    @pytest.mark.parametrize(
        "line",
        [
            "tokenizer=gpt2",
            "author=Smith",
            "KEY=os.getenv('OPENAI_API_KEY')",
            'KEY=""',
            "https://example.com:8080/path",
            # Settings about a secret, not the secret.
            "max_tokens: 4096",
            "tokens: 100",
            "TOKEN_LIMIT=4096",
            "auth_type: bearer",
            "secret_name: my-db-secret",
            "api_key_env: OPENAI_API_KEY",
            # Values that point at a secret instead of containing one.
            "export OPENAI_API_KEY=$OPENAI_API_KEY",
            "API_KEY=${API_KEY}",
            "password: <your-password>",
            "Authorization: Bearer <token>",
            "Authorization: {{secret:Authorization}}",
            'curl -H "Authorization: Bearer $TOKEN"',
            "GITHUB_TOKEN=${{ secrets.GITHUB_TOKEN }}",
        ],
    )
    def test_left_untouched(self, line):
        result = content_sanitizer.sanitize(line, "test.md")
        assert result.is_safe
        assert result.sanitized_content == line


class TestFindingKinds:
    """A finding names the most specific detector that matched the secret, as a stable code."""

    @pytest.mark.parametrize(
        ("line", "kinds"),
        [
            ("curl https://x.io/a?api_key=abc123def456ghi789", ["url_secret_parameter"]),
            ("x-api-key: abc123def456ghi789", ["authorization_header"]),
            ("mycli --password=hunter2hunter2", ["cli_secret_flag"]),
            ("password: hunter2hunter2", ["config_secret"]),
            ("OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz0123456789", ["api_token"]),
            ("DATABASE_URL=postgres://u:pw123456@db/x", ["database_credential"]),
            ("mycli --password=hunter2hunter2 /Users/alice/notes", ["cli_secret_flag", "absolute_path"]),
        ],
    )
    def test_kinds(self, line, kinds):
        assert content_sanitizer.sanitize(line, "test.md").redactions[0]["kinds"] == kinds

    def test_private_key_body_lines_are_private_key_findings(self):
        pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA0Z3VS5JJcds3xfn\n-----END RSA PRIVATE KEY-----"
        assert [r["kinds"] for r in content_sanitizer.sanitize(pem, "key.pem").redactions] == [["private_key"]]


class TestRuleTable:
    """The rule table reads the shared regexes by group number; a renumbered group must not go unnoticed."""

    @pytest.mark.parametrize("rule", _SECRET_RULES, ids=lambda rule: f"{rule.kind}:{rule.pattern.pattern[:24]}")
    def test_declared_groups_exist_in_the_pattern(self, rule):
        assert rule.pattern.groups >= max(rule.value_group, rule.name_group)

    def test_every_secret_kind_is_reachable(self):
        """A kind no detector can emit would carry a translation nobody ever sees."""
        emitted = {rule.kind for rule in _SECRET_RULES} | {"private_key", "absolute_path"}
        assert emitted == set(get_args(SecretKind))

    def test_overlapping_matches_are_unioned_so_no_part_of_a_secret_survives(self):
        def match(start, end, kind):
            return {"start": start, "end": end, "replacement": f"<{kind}>", "kind": kind}

        merged = _merge_overlaps(
            [match(0, 10, "api_token"), match(5, 20, "config_secret"), match(30, 35, "url_credential")]
        )
        assert [(m["start"], m["end"], m["kind"]) for m in merged] == [
            (30, 35, "url_credential"),
            (0, 20, "config_secret"),
        ]
