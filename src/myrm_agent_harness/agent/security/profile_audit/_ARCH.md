# profile_audit/

## Overview
Agent Profile configuration exposure aggregation audit engine. Deterministic rule-based static analysis that aggregates multiple security scanning dimensions into a unified risk score.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public API: `run_profile_audit`. | — |
| types.py | DTO | Input/output data transfer objects for the audit engine. | — |
| engine.py | Core | Orchestrates checkers, collects findings, delegates to scoring. | ✅ |
| scoring.py | Core | Computes aggregate risk score (0-100) and risk level from findings. | ✅ |

| Submodule | Description |
|-----------|-------------|
| checkers/ | Plugin-style checker modules. Each implements `BaseChecker`. |

### checkers/

| File | Role | Description |
|------|------|-------------|
| base.py | ABC | `BaseChecker` protocol — `check(input) -> list[AuditFinding]`. |
| tool_exposure.py | Checker | High-privilege built-in tool combination detection. |
| mcp_auth.py | Checker | MCP server authentication & transport security audit. |
| skill_aggregate.py | Checker | Aggregates skill scan summaries into profile-level findings. |
| subagent_risk.py | Checker | Sub-agent recursive delegation risk assessment. |
| cron_risk.py | Checker | Unattended cron job risk evaluation. |
| policy_gap.py | Checker | Security policy coverage gap detection. |

## Design Principles

1. **Pure computation**: No I/O, no database, no network calls. Receives DTOs, returns DTOs.
2. **Framework-agnostic input**: Input is a `ProfileAuditInput` DTO, not tied to any ORM or API model.
3. **Zero LLM dependency**: Deterministic rule engine. No token consumption.
4. **Plugin architecture**: New checkers implement `BaseChecker` and register in `engine.py`.
5. **Scoring transparency**: Each finding has severity + weight; final score is arithmetically derived.

## Key Dependencies

- None (pure computation module, zero external imports beyond stdlib and typing)
