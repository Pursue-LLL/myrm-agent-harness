"""Tests for the skill export content sanitizer.

Covers all pattern categories, edge cases, and the ignored_indices mechanism.
"""

import pytest

from myrm_agent_harness.agent.skills.security import (
    ContentSanitizer,
    Redaction,
    SanitizationResult,
    content_sanitizer,
)


class TestModuleExports:
    """Verify public API surface."""

    def test_singleton_instance(self):
        assert isinstance(content_sanitizer, ContentSanitizer)

    def test_sanitize_returns_result(self):
        result = content_sanitizer.sanitize("hello", "test.md")
        assert isinstance(result, SanitizationResult)

    def test_redaction_type(self):
        result = content_sanitizer.sanitize(
            "token = ghp_XxxYyyZzz1234567890abcdef12345678", "test.py"
        )
        assert len(result.redactions) == 1
        r = result.redactions[0]
        assert "line_number" in r
        assert "original" in r
        assert "redacted" in r
        assert "reason" in r


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
        result = content_sanitizer.sanitize(
            'export OPENAI_API_KEY="sk-proj-xxxyyyzzz"', "test.sh"
        )
        assert not result.is_safe
        assert "REDACTED" in result.sanitized_content

    def test_env_inline(self):
        result = content_sanitizer.sanitize(
            "API_KEY=my-secret-value-12345", ".env"
        )
        assert not result.is_safe


class TestJsonFields:
    """Detect JSON secret fields."""

    def test_json_api_key(self):
        result = content_sanitizer.sanitize(
            '"api_key": "my-secret-value-12345"', "config.json"
        )
        assert not result.is_safe
        assert "REDACTED" in result.sanitized_content

    def test_json_token(self):
        result = content_sanitizer.sanitize(
            '"token": "abc123def456"', "config.json"
        )
        assert not result.is_safe


class TestDatabaseConnections:
    """Detect database connection string passwords."""

    def test_postgres(self):
        result = content_sanitizer.sanitize(
            "postgres://admin:s3cr3t@db.example.com:5432/prod", "config.yaml"
        )
        assert not result.is_safe
        assert "***" in result.sanitized_content

    def test_mongodb(self):
        result = content_sanitizer.sanitize(
            "mongodb+srv://user:password123@cluster.mongodb.net/db", "config.yaml"
        )
        assert not result.is_safe


class TestUrlParameters:
    """Detect sensitive URL query parameters."""

    def test_api_key_param(self):
        result = content_sanitizer.sanitize(
            "https://api.example.com?api_key=sk_test_xxxyyy", "test.md"
        )
        assert not result.is_safe

    def test_token_param(self):
        result = content_sanitizer.sanitize(
            "https://example.com/cb?token=abc123&state=xyz", "test.md"
        )
        assert not result.is_safe


class TestCliFlags:
    """Detect CLI flags with secrets."""

    def test_api_key_flag(self):
        result = content_sanitizer.sanitize(
            "--api-key sk_test_1234567890", "test.sh"
        )
        assert not result.is_safe

    def test_token_flag(self):
        result = content_sanitizer.sanitize(
            "--token my_secret_token_value", "test.sh"
        )
        assert not result.is_safe


class TestTelegramBotTokens:
    """Detect Telegram bot tokens."""

    def test_bot_token(self):
        result = content_sanitizer.sanitize(
            "bot123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw", "test.md"
        )
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
        pem = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEpAIBAAKCAQEA0Z3VS5JJcds3xfn\n"
            "-----END RSA PRIVATE KEY-----"
        )
        result = content_sanitizer.sanitize(pem, "key.pem")
        assert not result.is_safe
        assert "...redacted..." in result.sanitized_content

    def test_preserves_pem_markers(self):
        pem = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEpAIBAAKCAQEA0Z3VS5JJcds3xfn\n"
            "-----END RSA PRIVATE KEY-----"
        )
        result = content_sanitizer.sanitize(pem, "key.pem")
        assert "-----BEGIN RSA PRIVATE KEY-----" in result.sanitized_content
        assert "-----END RSA PRIVATE KEY-----" in result.sanitized_content


class TestAbsolutePaths:
    """Detect absolute paths (macOS, Linux, Windows)."""

    def test_macos_path_line_start(self):
        result = content_sanitizer.sanitize(
            "/Users/alice/projects/my-api/config.json", "test.md"
        )
        assert not result.is_safe
        assert "REDACTED_PATH" in result.sanitized_content

    def test_linux_path_line_start(self):
        result = content_sanitizer.sanitize(
            "/home/admin/secrets/api.key", "test.md"
        )
        assert not result.is_safe

    def test_windows_path_line_start(self):
        result = content_sanitizer.sanitize(
            "C:\\Users\\John\\Documents\\secrets.txt", "test.md"
        )
        assert not result.is_safe

    def test_macos_path_after_space(self):
        result = content_sanitizer.sanitize(
            "cd /Users/alice/projects", "test.sh"
        )
        assert not result.is_safe

    def test_macos_path_after_equals(self):
        result = content_sanitizer.sanitize(
            "path=/Users/alice/config", "test.env"
        )
        assert not result.is_safe

    def test_system_path_not_detected(self):
        result = content_sanitizer.sanitize(
            "/System/Library/Frameworks/CoreFoundation.framework", "test.md"
        )
        assert result.is_safe

    def test_usr_local_not_detected(self):
        result = content_sanitizer.sanitize(
            "/usr/local/bin/python3", "test.md"
        )
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
        result = content_sanitizer.sanitize(
            "def hello():\n    return 'world'", "test.py"
        )
        assert result.is_safe


class TestIgnoredIndices:
    """Test user-toggle mechanism for selectively ignoring redactions."""

    def test_ignore_first_redaction(self):
        content = "/Users/alice/secret\nAuthorization: Bearer mytoken123"
        result = content_sanitizer.sanitize(content, "test.md", ignored_indices=[0])
        assert len(result.redactions) == 1
        assert result.redactions[0]["reason"] == "Authorization Header"

    def test_ignore_all(self):
        content = "key = ghp_XxxYyyZzz1234567890abcdef12345678"
        result = content_sanitizer.sanitize(content, "test.py", ignored_indices=[0])
        assert len(result.redactions) == 0
        assert result.is_safe


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
