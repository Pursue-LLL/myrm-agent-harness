# core/security/

## Overview
Foundational security primitives used across all layers. Zero dependency on agent/ internals, enabling toolkits/ to import security capabilities without coupling to the agent framework. Includes SSRF guards, audit, detection, and the in-memory credential vault for label-based password/TOTP injection.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Module docstring. Submodules imported directly. | — |
| audit.py | Core | Audit log writer — records security events to structured log. `SecurityDecision` carries optional `tool_call_id` that anchors a decision to the specific tool invocation that fired it (downstream lineage views attach the decision to the exact call). Tracks `PROTECTED_INSTRUCTION_ATTEMPT` and `PROTECTED_INSTRUCTION_ALLOWLIST_BLOCKED` events. `DecisionKind` is the closed set of decision names, and an AST test pins every `record_decision` literal in `src/` to it. Two name rules, each defined once: `is_blocking_decision()` (the decision refused the action it was about; the escalations that only close an auto-approval route, such as `FINANCIAL_GATE_ALLOWLIST_BLOCKED`, do not count; cron run summaries use it) and `is_policy_denial()` (the rule behind `policy_denial_total` and the control-plane deny totals; escalations and content protections count). | ✅ |
| redact/ | Core | Output redaction domain — compiled regexes (`patterns.py`) + bounded-replace engine & public APIs (`engine.py`) + facade (`__init__.py`): token prefixes, ENV/JSON/Auth/header/URL userinfo/query/bare-token/JWT, YAML/colon + form-urlencoded configs, word-boundary key validation, dotted-short-name keys (app.api.key=), CLI `=` flags, control-split bypass guard + double-match collapse guard; `redact_for_llm` (nested diagnostic value → str) + `redact_for_display` (args → dict). See `redact/_ARCH.md`. | ✅ |
| safe_exec.py | Core | Safe command execution — direct exec by default, shell fallback when needed. Env derived from caller env or ``os.environ`` is always passed through ``sanitize_env()`` (dangerous vars stripped) before credential overrides are injected post-sanitize. Process-group isolation + full-tree SIGKILL on timeout. | ✅ |
| shell_command_lexer.py | Core | The one reading of a shell command line, shared by the risk classifier, the approval-card span extractor, the destructive-action parser and the allow-always matcher (`toolkits/code_execution/security/`, `agent/security/command_allowlist_pattern.py`): where commands end, which words they have, which characters the shell interprets. Quote-, escape-, comment- and ANSI-C-aware; differentially fuzzed against bash 3.2 and 5.2. Pure functions, no dependencies. | ✅ |
| shell_wrapper_peel.py | Core | The one reading of the prefixes a shell accepts in front of a command, for the deny, ask and destructive directions: `direct_command_readings` reads through `sudo`/`doas`/`nohup`/`nice`/`env`/`setsid`/`stdbuf`/`ionice`/`xargs`/`watch` and leading `NAME=value` words, a shell `-c` script or `eval`, and each `$(...)`/backtick (`substitution_bodies`), which returns the command text of a real command substitution and steps into an arithmetic `$((...))` only to find a substitution nested inside it; `deny_readings` walks the whole string on top of it. The whole prefix chain is peeled with an index into one word list, so chain length never hides the inner command, is read in linear time, and copies no tail; only branching (nested substitutions and `-c` scripts) is capped, by `DENY_WRAPPER_DEPTH` / `MAX_COMMAND_READINGS`. Also the single home of the allow-direction `TRANSPARENT_WRAPPERS` (`command`, `time`, `timeout`) and its `unwrap_transparent_wrapper`, so the two directions cannot drift apart: widening this table is how a deny rule would be lifted. Pure functions over `shell_command_lexer`. | ✅ |
| tool_registry/ | Core | Tool metadata registry domain — permission mapping, canonical params, safety metadata, canonical tool group mapping (TOOL_GROUP_MAP/TOOL_TO_GROUP for skill conditional activation) + module-load safety coverage gate. See `tool_registry/_ARCH.md`. | ✅ |
| hitl_decision.py | Core | The one reading of the value a client sends back into a LangGraph `interrupt` (HITL answer SSOT). `is_approved` accepts exactly the shapes the product's clients produce — one decision for the pause (`{"decision": "approve" \| "reject"}`, WebUI approval drawer + HITL timer) and one decision per requested item (`{"decisions": [{"type": ...}]}`, chat tool-approval card, drawer subagent batch, IM buttons; every entry must approve) — plus the plain-text approval words, and denies every other shape, including an unreadable one. `rejection_feedback` reads the human's own words for a denial — `guidance` first (only the IM `/deny <reason>` path puts a person's words there, alongside its own generic `feedback` template), `feedback` as the fallback for every client that sends no `guidance` (approval drawer, chat card, desktop). `approval_guidance` reads the note a person wrote **with an approval** and reads `guidance` only, never `feedback`: on an approval `feedback` carries the HITL timer's own synthetic `Auto-approved: approval timeout (Ns)` and the bulk buttons' labels, so reading it would hand the model a machine's line as the person's words. Values are stripped and a blank or whitespace-only field is neither a reason nor a note, so a `guidance` of only spaces falls through to the real `feedback` for a denial and yields nothing for an approval. Pure functions, no dependencies. The tool-approval middleware keeps its own count-checked normalizer, which reads the same two shapes and is fail-closed. | ✅ |
| types.py | Core | Foundation security type hierarchy — SecurityConfig, PathPolicy, CapabilitySurface, CAPABILITY_SURFACE_PERMISSIONS, enums. | ✅ |
| device_policy.py | Core | Device security policy SSOT & dual-insurance batch risk assessment (`DeviceSecurityPolicy`, `BatchRiskAssessment`, `evaluate_batch_risk`). | ✅ |
| remote_ops_ledger.py | Core | Remote operations audit ledger and symmetric action recovery (`RemoteOpsActionRecord`, `ActionRecoveryHint`, `derive_recovery_hint`). | ✅ |
| missing_semantics.py | Core | Standardized missing semantics contract matrix (`MissingSemanticsPolicy`: `FAIL_CLOSED`, `FAIL_FAST`, `FALLBACK`), dynamic contract registry (`register_missing_semantics_contract`), structured diagnostic exporter (`to_diagnostic_dict`), and `@enforce_missing_semantics` gate decorator. | ✅ |
| credential_vault.py | Core | In-memory credential vault — label→password/TOTP resolution for browser/desktop injection (secrets never in LLM context). | ✅ |
| spend_governance.py | Core | Spend governance and cryptographic receipt primitives for Agent Commerce (parse_spend_amount, is_financial_or_spend_tool, is_irreversible_social_action, compute_action_digest, verify_action_digest, compute_entry_hash, SpendPolicy, SpendReceipt). | ✅ |

| Submodule | Description |
|-----------|-------------|
| path/ | Path security domain — glob matcher engine (`pattern.py`), generic path safety (`filesystem.py`), protected-path policy (`rules.py`), aggregation facade (`__init__.py`). See [path/_ARCH.md](path/_ARCH.md). |
| redact/ | Secret redaction domain — `patterns.py` (compiled regexes + shared replacers), `engine.py` (bounded-replace pipeline + public APIs), `__init__.py` (aggregation facade). |
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
| readonly_research_sandbox/ | Read-only research lease: while a session's lease is active only the lease's tools run (default-deny check, lease lifecycle, counters) ([readonly_research_sandbox/_ARCH.md](readonly_research_sandbox/_ARCH.md)). |
| auto_review_resolution/ | Diagnostic behind the message the model reads when a tool call is refused: reason code, allowed alternatives, four resolution branches; stateless ([auto_review_resolution/_ARCH.md](auto_review_resolution/_ARCH.md)). |
| ocap/ | Object-Capability (OCap) primitives: per-spawn signed handles enforced by the file and shell executors, with one-way attenuation from the parent handle ([ocap/_ARCH.md](ocap/_ARCH.md)). |

## Key Dependencies

- No internal dependencies (foundation layer)

## Consumers

- `toolkits/browser/session/interactor.py`, `toolkits/browser/tools/interact.py` — fill_credential
- `toolkits/browser/tools/semantic_dom_hitl.py`, `toolkits/computer_use/semantic_gate.py`, `toolkits/browser/tools/execute_script.py` — read a high-risk action / privileged script answer, and surface the person's refusal words when they gave any
- `agent/meta_tools/spawn_subagent/_delegate_batch.py`, `_delegate_cognitive.py` — read the batch cost answer, and surface the person's refusal words in `rejection_feedback` when they gave any
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
