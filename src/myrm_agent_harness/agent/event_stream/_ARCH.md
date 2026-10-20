# event_stream/

## Overview
Multi-part structured event stream, SQLite projector, and lossless session replayer suite.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Multi-part structured event stream, SQLite projector, and lossless session replayer suite. | — |
| `event_stream.py` | Core | Fine-grained multi-part asynchronous event stream bus with replay buffer. | ✅ |
| `part_types.py` | Core | Strongly typed atomic part data contracts for multi-part event streams. | ✅ |
| `session_replayer.py` | Core | Full lifecycle lossless session replayer and resumption breakpoint detector. | ✅ |
| `sqlite_projector.py` | Core | SQLite incremental state projector for fine-grained multi-part event streams. | ✅ |
