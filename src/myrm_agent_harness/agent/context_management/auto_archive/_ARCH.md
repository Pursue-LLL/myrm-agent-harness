# auto_archive/

## Overview
Account-wide idle chat session auto-archive policy evaluation, clamping, and sweep coordination.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Exports auto-archive policy evaluator, sweep coordinator, domain types, and facade suite. | — |
| `archive_policy_evaluator.py` | Core | Evaluates chat session eligibility against idle thresholds, pinning, running tasks, and user-creation. | ✅ |
| `archive_sweep_coordinator.py` | Core | Coordinates candidate batch filtering, execution callbacks, and sweep audit telemetry. | ✅ |
| `auto_archive_suite.py` | Core | Master facade coordinating policy evaluation, boundary clamping, and automated session sweeps. | ✅ |
| `auto_archive_types.py` | Types | Domain models, verdicts, exemption reason enums, session metadata snapshots, and configuration. | — |
