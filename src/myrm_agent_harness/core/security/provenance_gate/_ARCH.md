# provenance_gate/

## Overview

Session Entity Provenance Gate and Two-Stage Staging Approval Suite module. Harness core security subsystem inspired by Anthropic Commerce Agents (PROVENANCE_GATE & APPROVAL_GATE).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Session Entity Provenance Gate and Two-Stage Staging Approval Suite module — Harness core security subsystem inspired by Anthropic Commerce Agents (PROVENANCE_GATE & APPROVAL_GATE). | ✅ |
| caps_guardrail.py | Core | Hardcoded Python business caps and limits guardrail gate — Harness core security module inspired by Anthropic Commerce Agents (Caps & Limits Guardrails Gate). Enforces hard Python limits that cannot be bypassed via prompt injection. | ✅ |
| provenance_tracker.py | Core | Session entity provenance tracker preventing hallucinated or forged entity writes — Harness core security module inspired by Anthropic Commerce Agents (PROVENANCE_GATE). | ✅ |
| staging_gate.py | Core | Two-Stage Staging Approval Gate enforcing out-of-chat host signed token approvals — Harness core security module inspired by Anthropic Commerce Agents (APPROVAL_GATE & Out-of-Chat Interlock). | ✅ |
| types.py | Core | Type definitions for Session Entity Provenance Gate and Two-Stage Staging Approval Suite — Harness core security subsystem inspired by Anthropic Commerce Agents (PROVENANCE_GATE & APPROVAL_GATE). | ✅ |
| write_lock.py | Core | Serialized write lock manager preventing concurrent write races using WeakValueDictionary — Harness core concurrency & security module inspired by Anthropic Commerce Agents (_cart_locks / Serialized Write Locking). | ✅ |
