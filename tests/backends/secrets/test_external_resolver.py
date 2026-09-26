"""Unit tests for external secret reference resolver (1Password / Bitwarden)."""

from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.backends.secrets.external_resolver import (
    ExternalSecretResolutionError,
    invalidate_external_secret,
    is_external_secret_reference,
    resolve_external_secret,
)
from myrm_agent_harness.core.security.external_secrets import get_external_secrets_manager


@pytest.fixture(autouse=True)
def clean_cache() -> None:
    """Ensure in-memory cache is pristine for every test."""
    get_external_secrets_manager().clear_cache()
    yield
    get_external_secrets_manager().clear_cache()


class TestExternalSecretResolver:
    """Tests for 1Password op:// and Bitwarden bw:// URI resolution."""

    def test_is_external_secret_reference(self) -> None:
        assert is_external_secret_reference("op://Vault/OpenAI/credential") is True
        assert is_external_secret_reference('"op://Vault/OpenAI/credential"') is True
        assert is_external_secret_reference("'bw://my-openai-key'") is True
        assert is_external_secret_reference("bw://my-openai-key") is True
        assert is_external_secret_reference("bws://secret-uuid-1234") is True
        assert is_external_secret_reference("sk-proj-12345678") is False
        assert is_external_secret_reference("") is False
        assert is_external_secret_reference(None) is False

    @patch("subprocess.run")
    def test_resolve_op_secret_success_with_caching(self, mock_run: MagicMock) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "sk-op-resolved-key-value\n"
        mock_run.return_value = mock_proc

        result = resolve_external_secret("op://Vault/OpenAI/credential")
        assert result == "sk-op-resolved-key-value"

        # Second call hits memory cache: subprocess.run is NOT called again
        result_quoted = resolve_external_secret('"op://Vault/OpenAI/credential"')
        assert result_quoted == "sk-op-resolved-key-value"
        assert mock_run.call_count == 1

        # Invalidate cache and call again: should trigger a second subprocess.run
        invalidate_external_secret("op://Vault/OpenAI/credential")
        result_refetched = resolve_external_secret("op://Vault/OpenAI/credential")
        assert result_refetched == "sk-op-resolved-key-value"
        assert mock_run.call_count == 2

    @patch("subprocess.run")
    def test_resolve_bw_secret_success(self, mock_run: MagicMock) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "sk-bw-resolved-key-value\n"
        mock_run.return_value = mock_proc

        result = resolve_external_secret("bw://anthropic-api-key")
        assert result == "sk-bw-resolved-key-value"

        # Verify command and non-interactive environment isolation
        assert mock_run.call_count == 1
        args, kwargs = mock_run.call_args
        assert args[0] == ["bw", "get", "password", "anthropic-api-key"]
        assert kwargs["timeout"] == 4.0
        assert kwargs["env"]["BW_NO_PROMPT"] == "true"
        assert kwargs["env"]["OP_BIOMETRIC_UNLOCK_ENABLED"] == "false"

    @patch("subprocess.run")
    def test_resolve_bws_secret_success(self, mock_run: MagicMock) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = '{"value": "sk-bws-token"}\n'
        mock_run.return_value = mock_proc

        result = resolve_external_secret("bws://uuid-999")
        assert result == "sk-bws-token"

    @patch("subprocess.run")
    def test_resolve_cli_error(self, mock_run: MagicMock) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = "You are not signed in to 1Password."
        mock_run.return_value = mock_proc

        with pytest.raises(ExternalSecretResolutionError) as exc_info:
            resolve_external_secret("op://Vault/OpenAI/credential")
        assert "not signed in" in str(exc_info.value)

    def test_resolve_unsupported_scheme(self) -> None:
        with pytest.raises(ExternalSecretResolutionError) as exc_info:
            resolve_external_secret("vault://invalid/scheme")
        assert "Unsupported external secret URI" in str(exc_info.value)
