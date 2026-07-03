# interaction/

## Overview

Agent meta-tools for declarative UI rendering via the UIArtifact system.

Spec progressive disclosure (v3.1): slim `render_ui_tool` docstring + bundled
`A2UI_COMPONENT_REFERENCE.md` seeded to `{workspace}/.agent/docs/A2UI_REFERENCE.md`
when `enable_render_ui` is on (server `tool_setup`).

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Re-exports `render_ui`, `render_ui_tool`. | — |
| `a2ui_spec.py` | Core | Allowed types SSOT, bundled reference loader, workspace seed. | ✅ |
| `A2UI_COMPONENT_REFERENCE.md` | Config | Full component props manual (wheel force-include). | — |
| `render_ui_tool.py` | Core | A2UI declarative UI tool; fail-closed validation. | ✅ |

## Key Dependencies

- `agent/artifacts/` — `UIArtifact`, `get_ui_registry`, `UIComponentType`
