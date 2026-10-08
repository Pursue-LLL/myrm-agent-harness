# event_sourcing_replayer/

## Overview

Append-only immutable event log maintaining monotonic sequence numbers and hash chains.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Append-only session event sourcing and deterministic context replayer package. | ✅ |
| `append_only_event_log.py` | Core | Append-only immutable event log maintaining monotonic sequence numbers and hash chains. | ✅ |
| `deterministic_context_projector.py` | Core | Pure functional projector deriving exact model-visible context from event stream slices. | ✅ |
| `event_sourcing_replayer_suite.py` | Core | Suite managing append-only session event sourcing, step replaying, and audit certificates. | ✅ |
| `event_sourcing_types.py` | Types | Types and models for append-only session event sourcing and deterministic context replaying. | ✅ |
