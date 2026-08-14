# security/

## Overview

Security enforcement as middleware — security boundary rules injection and the
eight-layer guardrail defense (prompt guard, PII, leak detection, canary).

Detailed design: [MIDDLEWARE_SYSTEM.md](../MIDDLEWARE_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public exports for security middleware classes. | — |
| `security_boundary_middleware.py` | Core | Injects `SECURITY_BOUNDARY_SYSTEM_RULES` as an independent SystemMessage immediately after the main System Prompt (prompt-cache safe). | ✅ |
| `security_guardrail_middleware.py` | Core | Eight-layer defense integrated as an AgentMiddleware: circuit-breaker cognition, prompt guard, PII guard, tool-result redact, canary guard, leak detector, PII redact, history redact. | ✅ |

## Key Dependencies

- `agent.security.detection` — content_boundary, leak_detector, prompt_guard, pii
- `agent.middlewares._session_context` — canary token, privacy policy, terminal errors
