"""Edge-case tests for CredentialVault."""

import pytest

from myrm_agent_harness.toolkits.security.credential_vault import CredentialVault


def test_get_totp_token_missing_label_raises_key_error() -> None:
    vault = CredentialVault()
    with pytest.raises(KeyError, match="not found in vault"):
        vault.get_totp_token("missing-label")


def test_get_password_missing_label_raises_key_error() -> None:
    vault = CredentialVault()
    with pytest.raises(KeyError, match="not found in vault"):
        vault.get_password("missing-label")
