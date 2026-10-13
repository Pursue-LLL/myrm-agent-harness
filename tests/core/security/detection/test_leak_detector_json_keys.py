"""Leak detector: JSON credential fields, including prefixed keys (`SecretAccessKey`, `db_password`) used by cloud CLIs."""

from __future__ import annotations

import time

import pytest

from myrm_agent_harness.core.security.detection.leak_detector import redact_leaks, scan_for_leaks

AWS_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYzEXAMPLEKEY"
AWS_SESSION_TOKEN = (
    "AQoXdzELDDY//////////wEaoAK1wvxJY12r2IrDFT2IvAzTCn3zHoZ7YNtpiQLF0MqZye/qwjzP2iEXAMPLEbw/m3hsj8VBTkPORGvr9jM5"
    "sgP+w9IZWZnU+LWhmg+a5fDi2oTGUYcdg9uexQ4mtCHIHfi4citgqZTgco40Yqr4lIlo4V2b2Dyauk0eYFNebHtYlFVgAUj+7Indz3LU0aTW"
    "k1WKIjHmmMCIoTkyYp/k7kUG7moeEYKSitwQIi6Gjn+nyzM+PtoA3685ixzv0R7i5rjQi0YE0lf1oeie3bDiNHncmzosRM6SFiPzSvp6h/32"
    "xQuZsjcypmwsPSDtTPYcs0+YN/8BRi2/IcrxSpnWEXAMPLEXSDFTAQAM6Dl9zR0tXoybnlrZIwMLlMi1Kcgo5OytwU="
)


class TestPrefixedKeys:
    def test_iam_create_access_key_output_is_redacted(self) -> None:
        text = (
            '{\n    "AccessKey": {\n        "UserName": "Bob",\n        "Status": "Active",\n'
            f'        "SecretAccessKey": "{AWS_SECRET}",\n        "AccessKeyId": "AKIAIOSFODNN7EXAMPLE"\n    }}\n}}'
        )
        assert "json_credential" in scan_for_leaks(text)
        redacted = redact_leaks(text)
        assert AWS_SECRET not in redacted
        assert '"UserName": "Bob"' in redacted

    def test_sts_session_credentials_output_is_redacted(self) -> None:
        text = (
            f'{{"Credentials": {{"SecretAccessKey": "{AWS_SECRET}", "SessionToken": "{AWS_SESSION_TOKEN}", '
            '"Expiration": "2026-10-13T12:00:00Z", "AccessKeyId": "ASIAJEXAMPLEXEG2JICEA"}}'
        )
        redacted = redact_leaks(text)
        assert AWS_SECRET not in redacted
        assert AWS_SESSION_TOKEN not in redacted
        assert '"Expiration": "2026-10-13T12:00:00Z"' in redacted

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("SecretAccessKey", AWS_SECRET),
            ("SessionToken", AWS_SESSION_TOKEN),
            ("aws_secret_access_key", "abcdef1234567890abcd"),
            ("db_password", "superSecretCurrentPassword2024"),
            ("githubToken", "abcdef1234567890abcd"),
            ("x-api-key", "abcdef1234567890abcd"),
            ("s3.secret-key", "abcdef1234567890abcd"),
        ],
        ids=["aws-secret-key", "aws-session-token", "snake-case", "db-password", "camel-case", "dashed", "dotted"],
    )
    @pytest.mark.parametrize("quote", ['"', "'"], ids=["json", "python-repr"])
    def test_value_under_a_prefixed_key_is_flagged_and_redacted(self, key: str, value: str, quote: str) -> None:
        text = f"{{{quote}{key}{quote}: {quote}{value}{quote}}}"
        assert "json_credential" in scan_for_leaks(text)
        redacted = redact_leaks(text)
        assert value not in redacted
        assert "[REDACTED:json_credential]" in redacted
        assert redact_leaks(redacted) == redacted
        assert "json_credential" not in scan_for_leaks(redacted)


class TestKeyContainingTheValue:
    """The value is masked where it sits, not at its first occurrence, which may be inside the key."""

    SECRET = "superSecretCurrentPassword2024"

    @pytest.mark.parametrize(
        "template",
        ['{{"{secret}_token": "{secret}"}}', "{secret}_token={secret}"],
        ids=["json", "env"],
    )
    def test_key_stays_intact_and_value_is_masked(self, template: str) -> None:
        text = template.format(secret=self.SECRET)
        redacted = redact_leaks(text)
        assert redacted.startswith(text[: text.index("_token") + len("_token")])
        assert redacted.count(self.SECRET) == 1
        assert "[REDACTED:" in redacted


class TestNotACredential:
    @pytest.mark.parametrize(
        "text",
        [
            '{"setupToken": "Add GITHUB_TOKEN to the server settings to show pull request status"}',
            '{"jinaApiKey": "Jina Reader API 키 (선택)"}',
            '{"emptyApiKey": "API 키는 비어 있을 수 없습니다"}',
            '{"db_password": "short-value"}',
            '{"githubToken": "${GITHUB_TOKEN_FROM_VAULT}"}',
            '{"db_password": "YOUR_DB_PASSWORD_HERE"}',
            '{"apiKey": "<your-api-key-goes-here>"}',
            '{"sessionToken": "config.remote_session_token"}',
            '{"db_password": "settings.database_password_value"}',
            '{"tokenizer": "abcdef1234567890abcd"}',
            '{"secretary": "abcdef1234567890abcd"}',
        ],
        ids=[
            "english-ui-label",
            "korean-ui-label-with-latin-words",
            "korean-ui-message",
            "short-value",
            "template-placeholder",
            "your-placeholder",
            "angle-placeholder",
            "attribute-reference",
            "attribute-reference-under-prefixed-key",
            "key-merely-starts-with-a-sensitive-word",
            "key-merely-contains-a-sensitive-word",
        ],
    )
    def test_is_neither_flagged_nor_redacted(self, text: str) -> None:
        assert "json_credential" not in scan_for_leaks(text)
        assert redact_leaks(text) == text


class TestBareKeys:
    @pytest.mark.parametrize(
        "text",
        [
            '{"token": "Bearer abcdef1234567890abcdef12"}',
            '{"passphrase": "wrong wrong wrong"}',
            '{"clientSecret": "abcdef1234567890abcd"}',
            '{"api_key": "abcdef1234567890abcd"}',
        ],
        ids=["scheme-and-token", "spaced-passphrase", "camel-case-client-secret", "snake-case-api-key"],
    )
    def test_value_is_still_flagged_and_redacted(self, text: str) -> None:
        assert "json_credential" in scan_for_leaks(text)
        redacted = redact_leaks(text)
        assert "[REDACTED:json_credential]" in redacted
        assert redact_leaks(redacted) == redacted

    def test_reference_under_a_bare_key_is_not_a_credential(self) -> None:
        text = '{"apiKey": "settings.provider_api_key_value"}'
        assert "json_credential" not in scan_for_leaks(text)
        assert redact_leaks(text) == text


class TestLinearTime:
    """Scanners run on untrusted text, so no input may make the JSON rule backtrack badly."""

    @pytest.mark.parametrize(
        "text",
        [
            '"' + "a" * 200_000,
            '"token":"' + "a" * 200_000,
            '"' + "a-" * 100_000 + "token",
            '"a' * 100_000,
            '"token"' + " " * 200_000,
            '"token": "' * 20_000,
            '"' + "db_" * 100_000 + 'token": "' + "x" * 15,
        ],
        ids=["open-key", "open-value", "long-dashed-key", "many-quotes", "long-gap", "repeated-keys", "long-prefix"],
    )
    def test_adversarial_input_is_scanned_in_linear_time(self, text: str) -> None:
        started = time.perf_counter()
        scan_for_leaks(text)
        redact_leaks(text)
        assert time.perf_counter() - started < 1.0
