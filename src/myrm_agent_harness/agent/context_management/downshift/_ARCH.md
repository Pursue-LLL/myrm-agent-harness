# downshift/

## Overview
Context threshold-driven model downshift and handover memo governance.

Provides deterministic model tier switching (Premium -> Economy) when context usage or work unit consumption reaches defined thresholds, combined with zero-API-overhead handover memo generation from Session Notes and automatic fallback-up circuit breaking.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public export for downshift governor, models, and callbacks. | ✅ |
| `schemas.py` | Core | Domain models: `DownshiftTriggerMode`, `ModelTier`, `HandoffMemo`, `DownshiftConfig`, `DownshiftState`. | ✅ |
| `governor.py` | Core | `DownshiftGovernor`: Stateful threshold evaluation, memo builder from `SessionNotes`, manual revocation, and fallback-up handling. | ✅ |

## Key Dependencies
- `strategies.session_notes.schemas` (`SessionNotes`)
- `utils.logger_utils`
