# tests/examples/

## Overview
Non-shipping reference implementations and integration examples. Not part of the distributable `src/` package.

## File & Submodule Index

| File | Role | Description |
|------|------|-------------|
| progress_calculator_example.py | Reference | `WeightedTaskProgressCalculator` and `TimeBasedProgressCalculator` for custom sub-agent progress reporting |

## Key Dependencies

- Referenced conceptually by `agent/sub_agents/types.py` (`ProgressCalculator` protocol)
- See `tests/agent/sub_agents/test_auto_progress_log.py` for inline calculator usage in tests
