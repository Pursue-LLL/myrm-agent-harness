# tests/observability/

## Overview

Unit tests for **top-level** `myrm_agent_harness.observability` (metrics, diagnostics, tracing). Not `agent/observability/` EventBus tests — those live under `tests/agent/observability/`.

## File Index

| Area | Files |
|------|-------|
| diagnostics | `test_diagnostics_manager.py`, `test_diagnostics_protocols.py`, `test_probes.py`, `test_probes_extended.py` |
| tracing | `test_tracing.py` |
| metrics | `test_metrics.py`, `test_registry.py`, `test_goal_metrics.py` |
| auth | `test_auth_detector.py` |

## Key Dependencies

- `myrm_agent_harness.observability`
