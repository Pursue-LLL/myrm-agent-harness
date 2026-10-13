# cognitive_clock/

## Overview

Framework-level cooperative yielding signals that let background work pause for foreground activity.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Entry | Public exports for the cooperative pause signals | ✅ |
| `signals.py` | Core | Re-export of `infra/cooperative_signals.py` (single shared singleton). `toolkits/` imports from `infra/`, never from here. | ✅ |

## Key Dependencies

- `infra/cooperative_signals.py` (stdlib-only, framework-agnostic)
