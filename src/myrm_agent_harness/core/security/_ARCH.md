# core/security/

## Overview
Foundational security primitives used across all layers. Zero dependency on agent/ internals, enabling toolkits/ to import security capabilities without coupling to the agent framework.

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
| types.py | Core | Foundation security type hierarchy — SecurityConfig, PathPolicy, enums. | ✅ |

| Submodule | Description |
|-----------|-------------|
| detection/ | PII classification, content boundary marking, leak detection, prompt injection guard, pseudonymization. |
| guards/ | Session-level security guards — privacy tracker, SSRF guard. |

## Key Dependencies

- No internal dependencies (foundation layer)
