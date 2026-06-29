# commitment/

## Overview

Implicit commitment tracking — LLM extraction of follow-up items from conversations.
Harness supplies types and extraction; hosts implement `CommitmentStore` and delivery.

Detailed design: [COMMITMENT_SYSTEM.md](COMMITMENT_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Commitment tracking public API. | — |
| config.py | Config | Extraction thresholds and batch limits. | ✅ |
| extraction.py | Core | LLM-based commitment extraction from conversation messages. | ✅ |
| protocols.py | Core | `CommitmentStore` Protocol — host persistence contract. | ✅ |
| types.py | Core | `CommitmentRecord`, kinds, status lifecycle, due windows. | ✅ |

## Boundaries

- **Reuses**: injected async LLM callback only (no harness LLM factory coupling)
- **Does not import**: `agent/`, `runtime/`, `backends/`
- **Host implements**: `CommitmentStore`, session hook timing, REST/GUI, heartbeat delivery

## Key Dependencies

- `pydantic` (structured extraction and records)
- stdlib: `datetime`, `logging`
