"""Leak detector: references to a secret (code, templates, identifiers) are not secrets; real secrets still are."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.detection.leak_detector import redact_leaks, scan_for_leaks


class TestEnvCredentialReferences:
    @pytest.mark.parametrize(
        "text",
        [
            "token = _active_value(settings, name)",
            "secret = _resolve_secret(ctx)",
            "api_key = self._credentials.get_key_for_provider(name)",
            "token = {token_efficiency:.2f}",
            "secret = settings.some_long_attribute_name",
            "token=status.HTTP_400_BAD_REQUEST",
            "PASSWORD=$DATABASE_PASSWORD_FROM_VAULT",
            "Client(token=config.remote_token, transport_secret=transport_secret,",
            "Client(existing_delivery_secret=failure_alert_secret, password=self._config.password)",
        ],
        ids=[
            "private-call",
            "private-call-secret",
            "dotted-call",
            "format-field",
            "attribute",
            "constant",
            "shell-var",
            "argument-attribute-and-key-pass-through",
            "argument-name-and-attribute",
        ],
    )
    def test_reference_is_neither_flagged_nor_redacted(self, text: str) -> None:
        assert "env_credential" not in scan_for_leaks(text)
        assert redact_leaks(text) == text

    @pytest.mark.parametrize(
        "text",
        [
            "api_key = abcdef1234567890abcd",
            "API_SECRET=Zk9[mango]42abcdefgh",
            "DB_PASSWORD='Pa$$w0rd2024xyz!'",
            "token=aB3xK9mW2pQ7vL4nR8sT1yU6hD0jF5cG",
            "PASSWORD=superSecretCurrentPassword2024",
            "GITHUB_AUTH_TOKEN=ghp_placeholder_long_enough_val",
            "API_KEY=abcdef1234567890abcd, next",
        ],
        ids=[
            "lowercase-digits",
            "brackets",
            "dollar",
            "random",
            "camel-case-with-digits",
            "snake-case-env-value",
            "trailing-comma-in-prose",
        ],
    )
    def test_secret_value_is_still_flagged_and_redacted(self, text: str) -> None:
        assert "env_credential" in scan_for_leaks(text)
        assert "[REDACTED:env_credential]" in redact_leaks(text)


class TestHighEntropyReferences:
    @pytest.mark.parametrize(
        "text",
        [
            "raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)",
            "call(model_name=claude-sonnet-4-5-20250929-preview)",
            "class UserAuthenticationServiceImplementation2:",
            "contact alice.longname1@example-company-domain.com today",
            "GET docs/search?q=machine-learning-papers2024&page=2",
        ],
        ids=["status-constant", "keyword-slug", "class-name", "email", "query-string"],
    )
    def test_reference_is_not_a_high_entropy_token(self, text: str) -> None:
        assert "high_entropy_token" not in scan_for_leaks(text)
        assert redact_leaks(text) == text

    @pytest.mark.parametrize(
        "text",
        [
            "Found: aB3xK9mW2pQ7vL4nR8sT1yU6hD0jF5cG",
            "call(secret_blob=X7k9M2pQvL4nR8s1T6hD0jF5cGaB3xK9)",
        ],
        ids=["bare-token", "keyword-argument-secret"],
    )
    def test_random_token_is_still_flagged(self, text: str) -> None:
        assert "high_entropy_token" in scan_for_leaks(text)
        assert "[REDACTED:high_entropy_token]" in redact_leaks(text)
