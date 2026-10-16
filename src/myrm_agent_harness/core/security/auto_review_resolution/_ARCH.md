# auto_review_resolution/

## Overview

Diagnostic behind the message the model reads when a tool call is refused: a reason code, the lower-privilege alternatives that fit it, and the suggested one of four resolution branches (ask the user, try an alternative, hand over to the user, stop). Stateless: `agent/middlewares/approval/denial_diagnostic_bridge.py` renders each payload into the message and nothing here keeps it, so a long-lived process holds no per-denial state.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public API of the package. | ✅ |
| diagnostic_reporter.py | Core | `DenialDiagnosticReporter.generate_diagnostic`: derives the allowed alternatives and the suggested branch from a reason code and returns the payload. | ✅ |
| types.py | Core | `DenialReasonCodeEnum`, `ResolutionBranchEnum`, `DenialDiagnosticPayload`. | ✅ |

## Key Dependencies

- Standard library only.
- Consumed by `agent/middlewares/approval/denial_diagnostic_bridge.py`.
