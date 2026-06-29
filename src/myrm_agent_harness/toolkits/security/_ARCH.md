# security/

## Overview
Tool-level credential vault for execution-time secret resolution. Keeps decrypted
passwords and TOTP seeds in memory; LLM only sees credential labels.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Re-exports `CredentialVault`, `CredentialEntry`, `get_global_credential_vault` | ✅ |
| `credential_vault.py` | Core | In-memory vault and TOTP/password resolver for injection | ✅ |
## Dependencies

- No `agent/` imports (toolkits gate)
- Distinct from `toolkits/code_execution/security/` (shell/code sandbox validation)
