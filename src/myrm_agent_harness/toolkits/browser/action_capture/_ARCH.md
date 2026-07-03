# browser/action_capture/

## Overview

Agent-agnostic browser DOM action recorder — captures click/type/select/navigate into structured `ActionStep` sequences for the server Browser Skill Recording Wizard.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public exports: engine, types, serializer | ✅ |
| capture_engine.py | Core | Playwright CDP event listener + bridge | ✅ |
| types.py | Config | ActionType, ActionStep, CaptureSession | ✅ |
| serializer.py | Core | Session/step JSON + natural-language export | ✅ |

## Key Dependencies

- `toolkits/browser/` (Patchright Page)
- No imports from `agent/`, `runtime/`, or `backends/`
