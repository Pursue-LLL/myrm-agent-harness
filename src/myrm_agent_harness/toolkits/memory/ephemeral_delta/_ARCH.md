# ephemeral_delta/

## Overview

In-memory, session-scoped transient buffer for prompt-cache-preserving deltas.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Prompt-cache-preserving ephemeral session delta memory suite. | ✅ |
| `delta_store.py` | Core | In-memory, session-scoped transient buffer for prompt-cache-preserving deltas. | ✅ |
| `models.py` | Types | Types and models for ephemeral delta. | ✅ |
| `reconciler.py` | Core | Asynchronous reconciliation loop for persisting transient session deltas. | ✅ |
| `tail_injector.py` | Core | Injects active ephemeral session deltas at the tail of the final HumanMessage. | ✅ |
