# lease/

## Overview

In-flight task micro-lease and cascade termination suite.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | In-flight task micro-lease and cascade termination suite | ✅ |
| governor.py | Core | Task Lease Governor and Cascade Termination Executor — Maintains micro-lease tickets and real-time reverse resource indexes for in-flight tasks. Enforces execution-time assertions and triggers ≤100ms 3-level cascade termination (async task cancellation -> process SIGTERM/SIGKILL -> ephemeral context scrubbing). | ✅ |
| models.py | Core | Data models for in-flight task lease governor and cascade revocation suite — Immutable contracts defining micro-lease tickets, revocation events, and structured termination errors for execution-time privilege revocation. | ✅ |
