# commitment/

## Overview
Commitment tracking toolkit — implicit promise detection and follow-up. Extracts user commitments from conversations and tracks them for heartbeat delivery.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Commitment tracking public API. | — |
| config.py | Config | Commitment tracking configuration. | ✅ |
| extraction.py | Core | LLM-based commitment extraction from conversation messages. | ✅ |
| protocols.py | Core | CommitmentStore protocol — persistence interface. | ✅ |
| types.py | Config | Commitment data models. | ✅ |

## Key Dependencies

- `utils` (text_utils)
