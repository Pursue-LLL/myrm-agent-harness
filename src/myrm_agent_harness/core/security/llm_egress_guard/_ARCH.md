# llm_egress_guard/

## Overview

LLM Egress Default-Deny & Credential Binding Suite. Harness core security suite enforcing strict default-deny network egress.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | LLM Egress Default-Deny & Credential Binding Suite — Harness core security suite enforcing strict default-deny network egress. | ✅ |
| guard.py | Core | Fail-closed LLM Egress Guard enforcing explicit domain allowlists and credential binding — Harness core security guard ensuring zero un-audited or hijacked LLM/API outbound connections. | ✅ |
| policy_validator.py | Core | Domain and URL validation logic for LLM egress default-deny policies — Harness core security validator enforcing strict fail-closed egress boundaries. | ✅ |
| types.py | Core | Domain types and models for LLM Egress Default-Deny & Credential Binding — Harness core security domain models enforcing fail-closed LLM egress gating and strict destination-credential binding. | ✅ |
