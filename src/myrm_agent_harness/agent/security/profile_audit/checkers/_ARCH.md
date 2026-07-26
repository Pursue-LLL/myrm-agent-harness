# checkers/

## Overview
Profile audit checker plugin modules. Each checker is deterministic and returns
`AuditFinding[]` from typed `ProfileAuditInput`.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Exports checker implementations for engine registration. | — |
| `base.py` | Core | `BaseChecker` abstract interface (`check(input) -> list[AuditFinding]`). | ✅ |
| `tool_exposure.py` | Checker | Detects high-risk built-in tool exposure combinations. | ✅ |
| `mcp_auth.py` | Checker | Evaluates MCP authentication and transport guardrails. | ✅ |
| `skill_aggregate.py` | Checker | Converts skill-scan summaries into audit findings. | ✅ |
| `subagent_risk.py` | Checker | Scores recursive delegation and sub-agent risk patterns. | ✅ |
| `cron_risk.py` | Checker | Assesses unattended cron execution risk. | ✅ |
| `policy_gap.py` | Checker | Detects security policy coverage gaps. | ✅ |

## Dependencies

- `profile_audit/types.py`
- `profile_audit/checkers/base.py`
