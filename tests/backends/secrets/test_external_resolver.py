"""Unit tests for external secret reference resolver (1Password / Bitwarden)."""

from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.backends.secrets.external_resolver import (
    ExternalSecretResolutionError,
    is_external_secret_reference,
    resolve_external_secret,
)


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
    def test_resolve_op_secret_success(self, mock_run: MagicMock) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "sk-op-resolved-key-value\n"
        mock_run.return_value = mock_proc

        result = resolve_external_secret("op://Vault/OpenAI/credential")
        assert result == "sk-op-resolved-key-value"

        result_quoted = resolve_external_secret('"op://Vault/OpenAI/credential"')
        assert result_quoted == "sk-op-resolved-key-value"
        assert mock_run.call_count == 2

    @patch("subprocess.run")
    def test_resolve_bw_secret_success(self, mock_run: MagicMock) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "sk-bw-resolved-key-value\n"
        mock_run.return_value = mock_proc

        result = resolve_external_secret("bw://anthropic-api-key")
        assert result == "sk-bw-resolved-key-value"
        mock_run.assert_called_once_with(
            ["bw", "get", "password", "anthropic-api-key"],
            capture_output=True,
            text=True,
            timeout=6.0,
            check=False,
        )

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
