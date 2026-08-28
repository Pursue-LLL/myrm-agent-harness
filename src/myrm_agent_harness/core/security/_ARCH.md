# core/security/

## Overview
Foundational security primitives used across all layers. Zero dependency on agent/ internals, enabling toolkits/ to import security capabilities without coupling to the agent framework. Includes SSRF guards, audit, detection, and the in-memory credential vault for label-based password/TOTP injection.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Module docstring. Submodules imported directly. | — |
| audit.py | Core | Audit log writer — records security events to structured log. `SecurityDecision` carries optional `tool_call_id` that anchors a decision to the specific tool invocation that fired it (downstream lineage views attach the decision to the exact call). | ✅ |
| execution_policy.py | Core | Execution policy enums and interception contracts. | ✅ |
| path_security.py | Core | Path security — dangerous path sets, blocked system and Windows device names, boundary checks, safe path joining, runtime path coercion (`coerce_filesystem_path`). | ✅ |
| redact/ | Core | Output redaction domain — regex SSOT (`patterns.py`) + bounded-replace engine & public APIs (`engine.py`) + facade (`__init__.py`): token prefixes, ENV/JSON/Auth/header/URL userinfo/query/bare-token/JWT, YAML/colon + form-urlencoded configs, word-boundary key validation, dotted-short-name keys (app.api.key=), CLI `=` flags, control-split bypass guard + double-match collapse guard; `redact_for_llm` (nested diagnostic value → str) + `redact_for_display` (args → dict). See `redact/_ARCH.md`. | ✅ |
| safe_exec.py | Core | Safe command execution — direct exec by default, shell fallback when needed. Env derived from caller env or ``os.environ`` is always passed through ``sanitize_env()`` (dangerous vars stripped) before credential overrides are injected post-sanitize. Process-group isolation + full-tree SIGKILL on timeout. | ✅ |
| tool_registry/ | Core | Tool metadata registry domain — permission mapping, canonical params, safety metadata, canonical tool group mapping (TOOL_GROUP_MAP/TOOL_TO_GROUP for skill conditional activation) + module-load safety coverage gate. See `tool_registry/_ARCH.md`. | ✅ |
| types.py | Core | Foundation security type hierarchy — SecurityConfig, PathPolicy, enums. | ✅ |
| device_policy.py | Core | Device security policy SSOT & dual-insurance batch risk assessment (`DeviceSecurityPolicy`, `BatchRiskAssessment`, `evaluate_batch_risk`). | ✅ |
| remote_ops_ledger.py | Core | Remote operations audit ledger and symmetric action recovery (`RemoteOpsActionRecord`, `ActionRecoveryHint`, `derive_recovery_hint`). | ✅ |
| missing_semantics.py | Core | Standardized missing semantics contract matrix (`MissingSemanticsPolicy`: `FAIL_CLOSED`, `FAIL_FAST`, `FALLBACK`), dynamic contract registry (`register_missing_semantics_contract`), structured diagnostic exporter (`to_diagnostic_dict`), and `@enforce_missing_semantics` gate decorator. | ✅ |
| credential_vault.py | Core | In-memory credential vault — label→password/TOTP resolution for browser/desktop injection (secrets never in LLM context). | ✅ |

| Submodule | Description |
|-----------|-------------|
| redact/ | Secret redaction domain — `patterns.py` (compiled regex SSOT + shared replacers), `engine.py` (bounded-replace pipeline + public APIs), `__init__.py` (aggregation facade). |
| tool_registry/ | Tool registry domain — `registry.py` (tool safety SSOT: permission mapping, canonical params, safety metadata, tool groups) + `safety.py` (module-load coverage gate), `__init__.py` (aggregation facade). |
| detection/ | PII classification, content boundary marking, leak detection, prompt injection guard, pseudonymization. |
| persistence/ | Pre-write content scan SSOT — profiles for Memory / Wiki raw / Wiki publish ([persistence/_ARCH.md](persistence/_ARCH.md)). |
| privacy/ | 3-Level fail-closed privacy ladder validator for sandbox and workspace persistence ([privacy/_ARCH.md](privacy/_ARCH.md)). |
| integrity/ | Persistence write integrity, corruption detection, and atomic sealing validation ([integrity/_ARCH.md](integrity/_ARCH.md)). |
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
