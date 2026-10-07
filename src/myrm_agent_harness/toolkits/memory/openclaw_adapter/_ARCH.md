# openclaw_adapter/

## Overview
OpenClaw 2.0 Format Adapter & Crash Recovery Rescue Pipeline: multi-user & Swarm topology tree extraction, new SQLite/Memory schema mapping, read-only WAL isolation, integrity probe, and corrupted page auto-rescue.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public facade of the openclaw adapter subsystem. | ✅ |
| `crash_rescuer.py` | Core | Crash recovery engine for corrupted OpenClaw SQLite databases. | ✅ |
| `types.py` | Types | Typed data contracts for the openclaw adapter subsystem. | ✅ |
| `v2_parser.py` | Core | Parser and format adapter for OpenClaw 2.0 multi-user, Swarm topology, and structured memories. | ✅ |

## Key Dependencies

- None (self-contained within the package and the standard library)
