"""Security toolkit — in-memory credential vault for execution-time secret resolution.

[INPUT]
- credential_vault::CredentialVault, CredentialEntry, get_global_credential_vault (POS: in-memory vault)

[OUTPUT]
- Public API: CredentialVault, CredentialEntry, get_global_credential_vault

[POS]
Security toolkit entry point. Re-exports the credential vault used by browser
and desktop toolkits for label-based password/TOTP injection without exposing
secrets to the LLM.
"""

from .credential_vault import CredentialEntry, CredentialVault, get_global_credential_vault

__all__ = [
    "CredentialEntry",
    "CredentialVault",
    "get_global_credential_vault",
]
