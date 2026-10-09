# post_compaction_loop_guard/

## Overview

Post-Compaction Tool Loop Guard Suite (Item 331).
Protects autonomous agents from repeated tool invocation loops after context
compaction boundaries by preserving structured tool ledgers, issuing soft reminders,
and enforcing deterministic circuit breakers.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public symbols for Post-Compaction Tool Loop Guard Suite. | ✅ |
| `compaction_tool_ledger.py` | Ledger | Boundary tool signature extractor and prompt evidence block formatter. | ✅ |
| `post_compaction_loop_suite.py` | Facade | Unified facade suite coordinating ledger extraction and loop interception. | ✅ |
| `reexecution_detector.py` | Detector | Tool re-execution detector and deterministic circuit breaker. | ✅ |
| `tool_loop_types.py` | Types | Strongly-typed domain models, actions, and circuit-breaker exceptions. | ✅ |
