# core/security/

## Overview
Foundational security primitives used across all layers. Zero dependency on agent/ internals, enabling toolkits/ to import security capabilities without coupling to the agent framework. Includes SSRF guards, audit, detection, and the in-memory credential vault for label-based password/TOTP injection.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Module docstring. Submodules imported directly. | — |
| audit.py | Core | Audit log writer — records security events to structured log. `SecurityDecision` carries optional `tool_call_id` that anchors a decision to the specific tool invocation that fired it (downstream lineage views attach the decision to the exact call). Tracks `PROTECTED_INSTRUCTION_ATTEMPT` and `PROTECTED_INSTRUCTION_ALLOWLIST_BLOCKED` events. | ✅ |
| execution_policy.py | Core | Execution policy enums and interception contracts. | ✅ |
| redact/ | Core | Output redaction domain — regex SSOT (`patterns.py`) + bounded-replace engine & public APIs (`engine.py`) + facade (`__init__.py`): token prefixes, ENV/JSON/Auth/header/URL userinfo/query/bare-token/JWT, YAML/colon + form-urlencoded configs, word-boundary key validation, dotted-short-name keys (app.api.key=), CLI `=` flags, control-split bypass guard + double-match collapse guard; `redact_for_llm` (nested diagnostic value → str) + `redact_for_display` (args → dict). See `redact/_ARCH.md`. | ✅ |
| safe_exec.py | Core | Safe command execution — direct exec by default, shell fallback when needed. Env derived from caller env or ``os.environ`` is always passed through ``sanitize_env()`` (dangerous vars stripped) before credential overrides are injected post-sanitize. Process-group isolation + full-tree SIGKILL on timeout. | ✅ |
| tool_registry/ | Core | Tool metadata registry domain — permission mapping, canonical params, safety metadata, canonical tool group mapping (TOOL_GROUP_MAP/TOOL_TO_GROUP for skill conditional activation) + module-load safety coverage gate. See `tool_registry/_ARCH.md`. | ✅ |
| types.py | Core | Foundation security type hierarchy — SecurityConfig, PathPolicy, CapabilitySurface, CAPABILITY_SURFACE_PERMISSIONS, enums. | ✅ |
| device_policy.py | Core | Device security policy SSOT & dual-insurance batch risk assessment (`DeviceSecurityPolicy`, `BatchRiskAssessment`, `evaluate_batch_risk`). | ✅ |
| remote_ops_ledger.py | Core | Remote operations audit ledger and symmetric action recovery (`RemoteOpsActionRecord`, `ActionRecoveryHint`, `derive_recovery_hint`). | ✅ |
| missing_semantics.py | Core | Standardized missing semantics contract matrix (`MissingSemanticsPolicy`: `FAIL_CLOSED`, `FAIL_FAST`, `FALLBACK`), dynamic contract registry (`register_missing_semantics_contract`), structured diagnostic exporter (`to_diagnostic_dict`), and `@enforce_missing_semantics` gate decorator. | ✅ |
| credential_vault.py | Core | In-memory credential vault — label→password/TOTP resolution for browser/desktop injection (secrets never in LLM context). | ✅ |
| spend_governance.py | Core | Spend governance and cryptographic receipt primitives for Agent Commerce (parse_spend_amount, is_financial_or_spend_tool, is_irreversible_social_action, compute_action_digest, verify_action_digest, compute_entry_hash, SpendPolicy, SpendReceipt). | ✅ |

| Submodule | Description |
|-----------|-------------|
| path/ | Path security domain — glob matcher engine (`pattern.py`), generic path safety (`filesystem.py`), protected-path policy (`rules.py`), aggregation facade (`__init__.py`). See [path/_ARCH.md](path/_ARCH.md). |
| redact/ | Secret redaction domain — `patterns.py` (compiled regex SSOT + shared replacers), `engine.py` (bounded-replace pipeline + public APIs), `__init__.py` (aggregation facade). |
| tool_registry/ | Tool registry domain — `registry.py` (tool safety SSOT: permission mapping, canonical params, safety metadata, tool groups) + `safety.py` (module-load coverage gate), `__init__.py` (aggregation facade). |
| detection/ | PII classification, content boundary marking, leak detection, prompt injection guard, pseudonymization. |
| persistence/ | Pre-write content scan SSOT — profiles for Memory / Wiki raw / Wiki publish ([persistence/_ARCH.md](persistence/_ARCH.md)). |
| privacy/ | 3-Level fail-closed privacy ladder validator for sandbox and workspace persistence ([privacy/_ARCH.md](privacy/_ARCH.md)). |
| integrity/ | Persistence write integrity, corruption detection, and atomic sealing validation ([integrity/_ARCH.md](integrity/_ARCH.md)). |
| guards/ | Session-level security guards — privacy tracker, unified SSRF (`ssrf.py`), skill DLP allowlist (`url_allowlist.py`). |
| egress/ | Ephemeral sentinel voucher encoding/decoding and loopback egress proxy substitution for agent sandbox environments ([egress/_ARCH.md](egress/_ARCH.md)). |
| http/ | SSRF-protected outbound HTTP fetch — DNS pinning and redirect validation (`secure_fetch.py`). |
| external_secrets/ | Zero-disk plaintext external secrets vault gateway (1Password/Bitwarden) with LRU caching and 401 rotation ([external_secrets/_ARCH.md](external_secrets/_ARCH.md)). |
| ephemeral_credentials/ | Session-isolated ephemeral credential store and single-use zero-disk injection primitives with memory wipe ([ephemeral_credentials/_ARCH.md](ephemeral_credentials/_ARCH.md)). |

## Key Dependencies

- No internal dependencies (foundation layer)

## Consumers

- `toolkits/browser/session/interactor.py`, `toolkits/browser/tools/interact.py` — fill_credential
- `toolkits/computer_use/` — desktop fill_credential backends
- `myrm-agent-server/app/services/security/vault_credential_service.py` — sync decrypted credentials into global vault
- `agent/meta_tools/file_ops/validators/invariant_validator.py` — pre-write Goal protection
- `agent/goals/invariant_snapshot.py` — post-hoc tamper detection

Both protection layers resolve patterns through `path_pattern.py`, so the
pre-write guard and the post-hoc integrity check return the same verdict for
the same file. A rule that matches nothing is logged by
`invariant_snapshot.py` instead of being counted as coverage.

Every guard in this package — `is_sensitive_file`, `is_protected_instruction_file`
and `is_evidence_readonly_file` — inherits the matcher's case-insensitive
default. That default is the security invariant, not a convenience: APFS and
NTFS resolve `Key.Pem` and `key.pem` to one file, so a case-sensitive rule would
let a protected credential be reached by changing only its spelling. A caller
that genuinely needs case-distinguishing rules passes `case_sensitive=True`.

## Layout Convention

Package roots in this repository carry only three kinds of file: the outward facade,
a domain entry document (`_ARCH.md`), and the package `__init__.py`. Implementation
detail never sits flat at a package root.

- **One file for a domain** → a single flat module named after the domain
  (`audit.py`, `safe_exec.py`, `spend_governance.py`).
- **More than one file for a domain** → a subdirectory named after the domain
  (`detection/`, `egress/`, `redact/`, `path/`). Two files is already enough to warrant
  a subdirectory; the pattern is not reserved for large domains.
- **Renaming a domain's public import path** is a breaking change for every consumer,
  including sibling repositories. Add the subpackage, move the implementation, and
  update all call sites in one change — do not leave a compatibility shim behind, which
  would give the same API two addresses.

## Consumer Note

`agent/security/` contains thin shim modules that re-export several files from this package for stable `agent.security.*` import paths. Prefer `core.security` for new harness code outside agent middleware wiring.
