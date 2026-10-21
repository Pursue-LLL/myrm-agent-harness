# security/

## Overview
Agent security subsystem — 6-layer onion defense architecture.

Implementation split:
- **Agent-local** (`engine.py`, `checks.py`, `config.py`, …): orchestration wired into agent middlewares.
- **Core shims** (`audit.py`, `types.py`, `tool_registry.py`, `detection/*`, `guards/ssrf_guard.py` → `core/security/guards/ssrf.py`, …): re-exports from `core/security/` for stable `agent.security.*` import paths. Canonical implementations live in [../../core/security/_ARCH.md](../../core/security/_ARCH.md). New code outside agent middleware wiring should import from `core.security`.

Detailed design: [HITL_SYSTEM.md](HITL_SYSTEM.md)
Detailed design: [SECURITY_SYSTEM.md](SECURITY_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Agent security subsystem — 6-layer onion defense architecture. | ✅ |
| approval_flow.py | Core | Persistent allow-always, time-bound scoped allowlist, and in-memory session-scoped grants (permission/tool/exact/pattern matching, opportunistic expiry pruning, session isolation, find_matching_entry discovery, zero DB persistence for session-scoped grants, DB TTL cache). | ✅ |
| command_allowlist_pattern.py | Core | Shell command glob derivation, compound-command guard (read through `core.security.shell_command_lexer`: line breaks, `&`, redirects, substitution and grouping all count), parity vectors (`DERIVE_PATTERN_PARITY_VECTORS`). Patterns are derived from the inner command once `core.security.shell_wrapper_peel` has removed the transparent prefixes, so approving `timeout 30 pytest -q` grants `pytest -q *`, never `timeout 30 *`. | ✅ |
| audit.py | Core | Cross-cutting concern. Called from tool_interceptor_middleware and all | ✅ |
| channel_presets.py | Core | Decouples channel-specific security policy from the generic Permission Engine; merges user/agent flags. A cron job gets `file_write_tool` / `file_edit_tool` only when its declaration names `file_write`; the path zones then decide each write. | ✅ |
| checks.py | Core | Built-in security checks — Layer 2 & 2.5. Path policy (unified canonical boundary guard via `is_within_boundary`), URL scheme validation, protected instruction file write gate (`is_protected_instruction_file` -> `PermissionAction.ASK`), shell threat analysis. Pure functions returning (action, reason) tuples. | ✅ |
| config.py | Config | Deserialise SecurityConfig; `apply_remote_exposed_overlay`, `remote_exposed_permissions`. | ✅ |
| command_rules.py | Core | Shell-command rules of the permission engine: which tool inputs carry a command, the user deny-glob check, and the decision for one command line — every command judged on its own with the strictest decision winning, and a pattern ALLOW covering only a single plain command. Deny globs and ruleset rules are matched against every deny-direction reading produced by `core.security.shell_wrapper_peel`, so `timeout 30 kubectl delete ns prod` and `A=1 sudo kubectl delete ns prod` cannot slip past a rule that names the inner command. | ✅ |
| engine.py | Core | Layers 1–5 of the security architecture (Deny Precedence, Specificity Precedence matching specific tool_name before capability surface fallback, Command Denylist, PathPolicy, HITL, Spend Governance). Pure deterministic evaluation. `check_tool_path_policy` is the single path-zone verdict for a file tool's `path` (session grants overlaid), shared with the cron policy in `middlewares/approval/_cron_policy.py`. | ✅ |
| transcript_classifier.py | Core | Layer 5.5 — Reasoning-Blind Transcript Classifier for auto-mode. Evaluates tool calls using user intent, tool call sequence, taint labels, and trust context (trusted domains). No assistant reasoning. Forces deterministic output (temperature=0, max_tokens=200) regardless of upstream LLM config. | ✅ |
| trust_context.py | Core | RequestTrustContext protocol for remote admission path → tool restriction flags (consumed by agent-server overlay). | ✅ |
| path_security.py | Core | Re-export shim for `core.security.path` — keeps the `agent.security.*` import path stable. Logic-free; the forwarded surface is fixed by the core module's `__all__`. | ✅ |
| session_access.py | Core | Session-scoped HITL directory grants (ContextVar); grant/revoke; merge into PathPolicy at runtime; workspace-relative path resolve. | ✅ |
| ptc_verifier.py | Core | AST-based static analysis for PTC (Programmatic Tool Calling) scripts. Extracts MCP intent and enables Fast-Path Auto-Approve for read-only tools. | ✅ |
| rate_limiter.py | Core | Agent security rate limiter. Prevents brute-force attacks (e.g., WebUI login) with configurable rate | ✅ |
| redact.py | Core | Agent output redaction layer. Complements sanitize_env (source-level dangerous env var removal) with | ✅ |
| terminal_error_registry.py | Core | Turn-scoped terminal error state + durable God-Mode file injection channel (survives reset; runtime add() is memory-only). | ✅ |
| tool_registry.py | Core | Tool metadata registry: permission mapping, canonical params, safety metadata (6-dim), MCP annotation ingestion. resolve_safety_metadata uses 3-level fallback: built-in → MCP dynamic → fail-closed. | ✅ |
| types.py | Core | Foundation layer of the security type hierarchy. All other security modules import from here. Includes SecurityConfig factory methods (readonly/workspace/full_access/remote_exposed) and PathPolicy with workspace_label. | ✅ |
| managed_approval_policy.py | Core | Org floor MAP model + env/process loader (empty = local noop). | ✅ |
| managed_policy_gates.py | Core | Pure gate helpers: honor allowlist, global/per-model YOLO, effective auto_mode. | ✅ |
| batch_risk.py | Core | Batch risk evaluation and dual insurance policy check for approval queues. Pure deterministic functions. | ✅ |
| script_operand_verifier.py | Core | TOCTOU defense: extracts and validates mutable script file operand content SHA-256 digests across approval and execution (CVE-2026-32921). | ✅ |
| team_identity.py | Core | Team-shared conversation identity scope DTO (PERSONAL/SHARED, credential track, `ident:<id>` namespace). Pure types, no tools, no middleware wiring. | ✅ |

| Submodule | Description |
|-----------|-------------|
| workspace_trust/ | Folder bind trust + side-channel gate. See [workspace_trust/_ARCH.md](workspace_trust/_ARCH.md). |
| detection/ | Detection submodule. |
| guards/ | Session-level security guards integrated into tool_interceptor_middleware. |
| message_filtering/ | Message filtering framework for AI safety and compliance. |
| policy_generator/ | NL → SecurityConfig generation toolkit (prompts, parser, validator, explainer). Framework-level, LLM-agnostic. |
| profile_audit/ | Agent Profile configuration exposure aggregation audit engine. Deterministic rule-based static risk scoring. |
| single_use_tickets/ | Single-use authorization ticket manager and DSH 3-token chain content digest verification ([single_use_tickets/_ARCH.md](single_use_tickets/_ARCH.md)). |
## Key Dependencies

- `toolkits`
