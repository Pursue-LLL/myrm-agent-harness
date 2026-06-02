import pytest
import time
from myrm_agent_harness.toolkits.security.credential_vault import CredentialVault, get_global_credential_vault

def test_credential_vault_add_remove():
    vault = CredentialVault()
    vault.add_credential("test-label", password="password123")
    assert vault.get_password("test-label") == "password123"
    
    vault.remove_credential("test-label")
    with pytest.raises(KeyError):
        vault.get_password("test-label")

def test_credential_vault_clear():
    vault = CredentialVault()
    vault.add_credential("test1", password="p1")
    vault.add_credential("test2", password="p2")
    vault.clear()
    assert len(vault.list_labels()) == 0

def test_credential_vault_no_password():
    vault = CredentialVault()
    vault.add_credential("test-label", totp_seed="JBSWY3DPEHPK3PXP")
    with pytest.raises(ValueError, match="does not have a password"):
        vault.get_password("test-label")

def test_credential_vault_totp():
    vault = CredentialVault()
    # JBSWY3DPEHPK3PXP is base32 for "Hello!\xDE\xAD\xBE\xEF"
    vault.add_credential("test-totp", totp_seed="JBSWY3DPEHPK3PXP")
    
    token = vault.get_totp_token("test-totp")
    assert len(token) == 6
    assert token.isdigit()

def test_credential_vault_totp_invalid_seed():
    vault = CredentialVault()
    vault.add_credential("test-totp", totp_seed="INVALID_SEED_!@#")
    with pytest.raises(ValueError, match="Failed to generate TOTP"):
        vault.get_totp_token("test-totp")

def test_credential_vault_no_totp():
    vault = CredentialVault()
    vault.add_credential("test-label", password="password123")
    with pytest.raises(ValueError, match="does not have a TOTP seed"):
        vault.get_totp_token("test-label")

def test_global_vault():
    vault = get_global_credential_vault()
    assert isinstance(vault, CredentialVault)
