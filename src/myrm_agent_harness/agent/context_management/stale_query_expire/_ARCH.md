# stale_query_expire/

## Overview

End-to-end suite orchestrating query context expiration in persistent long-running sessions.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Stale query context expiration package. | ✅ |
| `query_context_types.py` | Types | Strongly typed contracts for persistent session query context and staleness tracking. | ✅ |
| `stale_query_context_suite.py` | Core | End-to-end suite orchestrating query context expiration in persistent long-running sessions. | ✅ |
| `stale_query_expiry_engine.py` | Core | Engine evaluating query context aging through dual turn-distance and TTL criteria. | ✅ |
