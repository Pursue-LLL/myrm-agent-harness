# completion/

## Overview

Completion guard subsystem — finish gate, code verification, external evidence,
deliverable write claims, and mixed-message early termination.

Detailed design: [MIDDLEWARE_SYSTEM.md](../MIDDLEWARE_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public exports for CompletionGuard and helpers. | — |
| `completion_guard.py` | Core | Finish gate + Mixed Message Guard + independent sandbox re-run for code tasks. Orchestrates checklist, external evidence, and deliverable write verification. | ✅ |
| `completion_guard_checklist.py` | Internal | Verification command classification, checklist builder, temporal ordering analysis. | ✅ |
| `completion_guard_external_evidence.py` | Internal | Freshness-sensitive external evidence gate (web/browser + MCP PTC bash via ``skills.mcp_*``). | ✅ |
| `deliverable_write_verifier.py` | Internal | Zero-call deliverable write claim detection. | ✅ |

## Key Dependencies

- `agent.middlewares.tool_interceptor_middleware` — LoopGuard CallRecord window
- `agent.security.guards.loop_guard` — CallRecord, ToolGroup
- `toolkits.code_execution` — independent verification re-run sandbox
