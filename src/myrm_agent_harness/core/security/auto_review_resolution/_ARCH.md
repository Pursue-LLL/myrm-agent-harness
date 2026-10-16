# auto_review_resolution/

## Overview

Strict typing applied: No `Any` types allowed. src/myrm_agent_harness/core/security/auto_review_resolution/__init__.py [INPUT] .diagnostic_reporter, .types [OUTPUT] Public API exports for auto-review denial resolution subsystem Strict typing applied: No `Any` types allowed.

Stateless by design: the reporter builds a diagnostic payload that `agent/middlewares/approval/denial_diagnostic_bridge.py` renders into the denial message the model reads, and nothing here keeps it afterwards, so a long-lived process holds no per-denial state.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Strict typing applied: No `Any` types allowed — src/myrm_agent_harness/core/security/auto_review_resolution/__init__.py [INPUT] .diagnostic_reporter, .types [OUTPUT] Public API exports for auto-review denial resolution subsystem Strict typing applied: No `Any` types allowed. | ✅ |
| diagnostic_reporter.py | Core | Synthesizes structured, LLM-reflective Denial Diagnostic Payloads with actionable — src/myrm_agent_harness/core/security/auto_review_resolution/diagnostic_reporter.py [INPUT] time, uuid, typing, .types (DenialDiagnosticPayload, DenialReasonCodeEnum, ResolutionBranchEnum) [OUTPUT] DenialDiagnosticReporter Synthesizes structured, LLM-reflective Denial Diagnostic Payloads with actionable context, allowed security alternatives, and recommended resolution branches. Strict typing applied: No `Any` types allowed. | ✅ |
| types.py | Core | Data structures for the Auto-Review Denial diagnostic and its four adaptive resolution branches — src/myrm_agent_harness/core/security/auto_review_resolution/types.py [INPUT] dataclasses, enum, typing [OUTPUT] DenialReasonCodeEnum, ResolutionBranchEnum, DenialDiagnosticPayload Data structures for the Auto-Review Denial diagnostic and its four adaptive resolution branches. Strict typing applied: No `Any` types allowed. | ✅ |
