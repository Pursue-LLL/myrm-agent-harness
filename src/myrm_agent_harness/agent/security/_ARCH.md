# security/

## Overview
Agent security subsystem — 6-layer onion defense architecture.

Implementation split:
- **Agent-local** (`engine.py`, `checks.py`, `config.py`, …): orchestration wired into agent middlewares.
- **Core shims** (`audit.py`, `types.py`, `tool_registry.py`, `detection/*`, `guards/ssrf_guard.py`, …): thin re-exports from `core/security/` so legacy `agent.security.*` import paths stay stable. Canonical implementations live in [../../core/security/_ARCH.md](../../core/security/_ARCH.md). New code should import from `core.security` when outside agent middleware wiring.

Detailed design: [HITL_SYSTEM.md](HITL_SYSTEM.md)
Detailed design: [SECURITY_DESIGN.md](SECURITY_DESIGN.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Agent security subsystem — 6-layer onion defense architecture. | — |
| approval_flow.py | Core | Core component for "Always Allow" feature in Human-in-the-Loop approval system. | ✅ |
| audit.py | Core | Cross-cutting concern. Called from tool_interceptor_middleware and all | ✅ |
| channel_presets.py | Core | Decouples channel-specific security policy from the generic Permission Engine. | ✅ |
| checks.py | Core | Built-in security checks — Layer 2 & 2.5. Path policy, URL scheme validation, shell threat analysis. Pure functions returning (action, reason) tuples. | ✅ |
| config.py | Config | Called at application startup and on config updates. Pure functions. | ✅ |
| engine.py | Core | Layers 1–5 of the security architecture. Pure deterministic evaluation — | ✅ |
| execution_policy.py | Core | Execution policy and suspension abstraction. Defines low-level policy enums and interception contrac | ✅ |
| transcript_classifier.py | Core | Layer 5.5 — Reasoning-Blind Transcript Classifier for auto-mode. Evaluates tool calls using user intent, tool call sequence, taint labels, and trust context (trusted domains). No assistant reasoning. Forces deterministic output (temperature=0, max_tokens=200) regardless of upstream LLM config. | ✅ |
| path_security.py | Core | Path security — single source of truth for dangerous paths, boundary checks, and safe path joining. | ✅ |
| ptc_verifier.py | Core | AST-based static analysis for PTC (Programmatic Tool Calling) scripts. Extracts MCP intent and enables Fast-Path Auto-Approve for read-only tools. | ✅ |
| rate_limiter.py | Core | Agent security rate limiter. Prevents brute-force attacks (e.g., WebUI login) with configurable rate | ✅ |
| redact.py | Core | Agent output redaction layer. Complements sanitize_env (source-level dangerous env var removal) with | ✅ |
| safe_exec.py | Core | Layer 2 enhancement. Called from: | ✅ |
| terminal_error_registry.py | Core | Turn-scoped terminal error storage with persistence. | ✅ |
| tool_registry.py | Core | Tool metadata registry: permission mapping, canonical params, safety metadata (6-dim), MCP annotation ingestion. resolve_safety_metadata uses 3-level fallback: built-in → MCP dynamic → fail-closed. | ✅ |
| types.py | Core | Foundation layer of the security type hierarchy. All other security modules import from here. Includes SecurityConfig factory methods (readonly/workspace/full_access) and PathPolicy with workspace_label. | ✅ |

| Submodule | Description |
|-----------|-------------|
| detection/ | Detection submodule. |
| guards/ | Session-level security guards integrated into tool_interceptor_middleware. |
| message_filtering/ | Message filtering framework for AI safety and compliance. |
| policy_generator/ | NL → SecurityConfig generation toolkit (prompts, parser, validator, explainer). Framework-level, LLM-agnostic. |

## Key Dependencies

- `toolkits`
