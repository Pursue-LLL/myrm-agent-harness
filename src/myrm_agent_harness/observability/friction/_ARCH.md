# observability/friction/

## Overview

Zero-LLM Agent task execution friction point telemetry and Eval Lab co-evolution pipeline. Extracts, categorizes, aggregates, and converts real-world execution friction (format parse errors, spill overflows, tool timeouts, permission denials, stuck loops) into standardized EvalCases.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Re-exports TaskFrictionEvent, FrictionExtractor, FrictionAggregator, and eval_bridge. | ✅ |
| `types.py` | Core | Foundation type system: FrictionCategory, TaskFrictionEvent, FrictionSummary. | ✅ |
| `extractor.py` | Core | FrictionExtractor for zero-LLM deterministic extraction from event streams and exceptions. | ✅ |
| `aggregator.py` | Core | Statistical aggregation engine computing friction distributions, top offending tools, and hotspots. | ✅ |
| `eval_bridge.py` | Core | Model co-evolution bridge converting TaskFrictionEvents into repeatable EvalCases. | ✅ |

## Key Dependencies

- `eval` (via eval_bridge for EvalCase conversion)
