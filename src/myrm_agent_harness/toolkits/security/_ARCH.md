# security/

## Overview
Tool-level credential vault for execution-time secret resolution. Keeps decrypted
passwords and TOTP seeds in memory; LLM only sees credential labels.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `credential_vault.py` | Core | In-memory vault and TOTP/password resolver for injection | ✅ |
## Dependencies

- No `agent/` imports (toolkits gate)
- Distinct from `toolkits/code_execution/security/` (shell/code sandbox validation)
