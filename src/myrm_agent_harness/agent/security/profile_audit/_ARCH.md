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
| checkers/ | Plugin-style checker modules. Each implements `BaseChecker`. See [checkers/_ARCH.md](checkers/_ARCH.md). |


## Design Principles

1. **Pure computation**: No I/O, no database, no network calls. Receives DTOs, returns DTOs.
2. **Framework-agnostic input**: Input is a `ProfileAuditInput` DTO, not tied to any ORM or API model.
3. **Zero LLM dependency**: Deterministic rule engine. No token consumption.
4. **Plugin architecture**: New checkers implement `BaseChecker` and register in `engine.py`.
5. **Scoring transparency**: Each finding has severity + weight; final score is arithmetically derived.

## Key Dependencies

- None (pure computation module, zero external imports beyond stdlib and typing)
