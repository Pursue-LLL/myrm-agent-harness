# tool_validation/

## Overview
Mixed batch tool validation, auto-repair, and role alternation guard suite.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Mixed batch tool validation, auto-repair, and role alternation guard suite. | — |
| `batch_validator.py` | Core | Mixed batch tool validator with 3-strike partial exit and role alternation enforcement. | ✅ |
| `fuzzy_repair.py` | Core | Fuzzy tool name auto-repair and tool-call ID uniquification engine. | ✅ |
| `role_alternation_guard.py` | Core | Role alternation invariants verifier and interrupted sequence closing guard. | ✅ |
| `validation_types.py` | Core | Strongly typed data contracts for mixed batch tool validation and role alternation guard. | ✅ |
