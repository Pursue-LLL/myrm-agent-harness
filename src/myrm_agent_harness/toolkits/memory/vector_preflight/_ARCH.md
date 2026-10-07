# vector_preflight/

## Overview
Vector Store Preflight Dimension Integrity & IPv4 Loopback Sanitizer: IPv4 loopback sanitization eliminating IPv6 ::1 container traps, preflight dynamic embedding dimension sampling, and rigid schema mismatch prevention.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public facade of the vector preflight subsystem. | ✅ |
| `probe.py` | Core | Rigidly evaluates and asserts vector dimension consistency before store operations. | ✅ |
| `sanitizer.py` | Core | Sanitizes connection endpoints to eliminate IPv6 ::1 localhost resolution traps in container environments. | ✅ |
| `types.py` | Types | Typed data contracts for the vector preflight subsystem. | ✅ |

## Key Dependencies

- None (self-contained within the package and the standard library)
