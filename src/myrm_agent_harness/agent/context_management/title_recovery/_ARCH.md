# title_recovery/

## Overview
Invalid LLM generated title recovery, structural taxonomy classification, and provisional retry gate.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Exports title recovery taxonomy, retry gate, models, and master facade suite. | — |
| `invalid_title_taxonomy.py` | Core | Classifies structural defects (CoT leak, option menus, conversational prose) and cleanses raw titles. | ✅ |
| `provisional_title_retry_gate.py` | Core | Stateful retry gate deferring dirty database writes and triggering capped deterministic fallback. | ✅ |
| `title_recovery_suite.py` | Core | Master facade coordinating taxonomy classification, provisional delay, and deterministic fallbacks. | ✅ |
| `title_recovery_types.py` | Types | Domain contracts, reason enums, validation models, state tracking, and configuration. | — |
