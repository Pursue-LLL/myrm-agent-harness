# hitl_fail_closed/

## Overview

Public API for HITL Approval Fail-Closed Safety Gate & Non-Bypassable Guard Suite. Harness core security module package entrypoint.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public API for HITL Approval Fail-Closed Safety Gate & Non-Bypassable Guard Suite — Harness core security module package entrypoint. | ✅ |
| pipeline.py | Core | Two-Phase HITL Approval Pipeline enforcing strict Fail-Closed semantics and invariant guards — Harness core security pipeline guaranteeing zero silent approval on communication failure and enforcing non-bypassable secondary safety invariants. | ✅ |
| secondary_guard.py | Core | Non-Bypassable Secondary Guard enforcing physical and invariant security boundaries — Harness core security barrier that cannot be relaxed or bypassed by human approval or prompts. | ✅ |
| types.py | Core | Domain types and models for HITL Approval Fail-Closed Safety Gate & Non-Bypassable Guard — Harness core security domain models ensuring human-in-the-loop approvals strictly default to REJECTED on disconnection/timeout and invariant guards cannot be bypassed. | ✅ |
