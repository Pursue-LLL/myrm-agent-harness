# command_explainer/

## Overview
Shell command span extraction and per-segment risk levels for HITL approval UI.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| types.py | DTO | CommandSpan, SpanRiskLevel, SpanRiskReason | — |
| extract.py | Core | Spans (quote-aware split, 128KB cap), risk levels + i18n reason codes via risk_classifier; exports MAX_COMMAND_SPAN_SOURCE_CHARS | ✅ |
| __init__.py | Package | Public exports | — |

## Dependencies

- `security.risk_classifier` (POS: shell command risk classification)
