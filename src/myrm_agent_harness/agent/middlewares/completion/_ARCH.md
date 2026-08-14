# completion/

## Overview

Completion guard subsystem — finish gate, code verification, external evidence,
deliverable write claims, and mixed-message early termination.

Detailed design: [MIDDLEWARE_SYSTEM.md](../MIDDLEWARE_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public exports for CompletionGuard and helpers. | — |
| `completion_guard.py` | Core | Finish gate + Mixed Message Guard + independent sandbox re-run for code tasks. Orchestrates checklist, external evidence, and deliverable write verification. Mixed Message preserves effectful calls (`is_mutating_tool`, registry fail-closed) and interaction/UI carriers; only guaranteed side-effect-free non-interactive read-only tools are stripped. | ✅ |
| `completion_guard_safety.py` | Internal | Effectful tool detection SSOT (`is_mutating_tool`) with static mutation/interaction-UI alias sets and registry fail-closed fallback; consumed by Mixed Message Guard and server Cron post-run verification. | ✅ |
| `completion_guard_checklist.py` | Internal | Verification command classification, checklist builder, temporal ordering analysis. | ✅ |
| `completion_guard_external_evidence.py` | Internal | Freshness-sensitive external evidence gate (web/browser + MCP: PTC bash via ``skills.mcp_*`` and Direct FC via ``mcp__{server}__{tool}``; internal code-task requests are exempted from external-evidence requirements). | ✅ |
| `deliverable_write_verifier.py` | Internal | Zero-call deliverable write claim detection. | ✅ |

## Key Dependencies

- `agent.middlewares.tool_interceptor_middleware` — LoopGuard CallRecord window
- `agent.security.guards.loop_guard` — CallRecord, ToolGroup
- `toolkits.code_execution` — independent verification re-run sandbox
