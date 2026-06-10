# command_explainer/

## Overview
Shell command span extraction, per-segment risk levels, and bilingual human-readable
explanations for HITL approval UI.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| types.py | DTO | CommandSpan, SpanRiskLevel, SpanRiskReason | — |
| extract.py | Core | Spans (quote-aware split, 128KB cap), risk levels + i18n reason codes + plain explanation via humanize; exports build_shell_approval_fields | ✅ |
| humanize.py | Core | Rule-based bilingual (en/zh) command explanation generator; zero-LLM, pure dict lookup | ✅ |
| __init__.py | Package | Public exports | — |

## Dependencies

- `security.risk_classifier` (POS: shell command risk classification)

## Data Flow

```
build_shell_approval_fields(tool_name, redacted_args)
  → extract_command_spans(shell_text)       → CommandSpan[]
  → _classify_span_risk_pairs(...)          → SpanRiskLevel[], SpanRiskReason[]
  → humanize_command(shell_text, spans, levels)  → BilingualExplanation | None
  → returns { command_spans, command_span_risks, command_span_reasons, plain_explanation? }
```

Frontend receives `plain_explanation: {en, zh}` and renders it below the
highlighted command in ShellCommandDisplay.
