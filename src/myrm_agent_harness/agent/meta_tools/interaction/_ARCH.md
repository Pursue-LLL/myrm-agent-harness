# interaction/

## Overview

Agent meta-tools for declarative UI rendering via the UIArtifact system.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Re-exports `render_ui`, `render_ui_tool`. | — |
| `render_ui_tool.py` | Core | A2UI declarative UI tool; registers `UIArtifact` into agent artifact context. | ✅ |

## Key Dependencies

- `agent/artifacts/` — `UIArtifact`, `get_ui_registry`, component types
