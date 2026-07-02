# core/security/

## Overview
Foundational security primitives used across all layers. Zero dependency on agent/ internals, enabling toolkits/ to import security capabilities without coupling to the agent framework. Includes SSRF guards, audit, detection, and the in-memory credential vault for label-based password/TOTP injection.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Module docstring. Submodules imported directly. | — |
| audit.py | Core | Audit log writer — records security events to structured log. | ✅ |
| execution_policy.py | Core | Execution policy enums and interception contracts. | ✅ |
| path_security.py | Core | Path security — dangerous path sets, boundary checks, safe path joining. | ✅ |
| redact.py | Core | Output redaction layer — sanitizes sensitive patterns in agent output. | ✅ |
| safe_exec.py | Core | Safe execution primitives — sandboxed code evaluation with resource limits. | ✅ |
| tool_registry.py | Core | Tool metadata registry — permission mapping, canonical params, safety metadata, canonical tool group mapping (TOOL_GROUP_MAP/TOOL_TO_GROUP for skill conditional activation). | ✅ |
| tool_registry_safety.py | Internal | Module-load built-in tool safety metadata coverage check. | ✅ |
| types.py | Core | Foundation security type hierarchy — SecurityConfig, PathPolicy, enums. | ✅ |
| credential_vault.py | Core | In-memory credential vault — label→password/TOTP resolution for browser/desktop injection (secrets never in LLM context). | ✅ |

| Submodule | Description |
|-----------|-------------|
| detection/ | PII classification, content boundary marking, leak detection, prompt injection guard, pseudonymization. |
| guards/ | Session-level security guards — privacy tracker, unified SSRF (`ssrf.py`), skill DLP allowlist (`url_allowlist.py`). |
| http/ | SSRF-protected outbound HTTP fetch — DNS pinning and redirect validation (`secure_fetch.py`). |

## Key Dependencies

- No internal dependencies (foundation layer)

## Consumers

- `toolkits/browser/session/interactor.py`, `toolkits/browser/tools/interact.py` — fill_credential
- `toolkits/computer_use/` — desktop fill_credential backends
- `myrm-agent-server/app/services/security/vault_credential_service.py` — sync decrypted credentials into global vault

## Consumer Note

`agent/security/` contains thin shim modules that re-export several files from this package for stable `agent.security.*` import paths. Prefer `core.security` for new harness code outside agent middleware wiring.
