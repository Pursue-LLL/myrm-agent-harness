# drain_and_restart/

## Overview
Graceful drain and session-preserving restart suite.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Graceful drain and session-preserving restart suite. | — |
| `drain_types.py` | Core | Domain types for graceful drain and session-preserving restart suite. | ✅ |
| `graceful_drain.py` | Core | Graceful service drain coordinator for zero-downtime maintenance. | ✅ |
| `restart_state_machine.py` | Core | Clean generation restart state machine with rollback protection. | ✅ |
| `restart_verifier.py` | Core | Independent health verification prober for clean service generations. | ✅ |
