# execution/

## Overview
Coordinate-based fallback execution when semantic AX invoke fails on a @dref element.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| healer.py | Core | BBox center click/type fallback via ComputerBackend | ✅ |

## Dependencies

- `element_ref/types.py` (POS: ElementRef with BBox)
- `types.py` (POS: ActionResult, ModifierKey)
- Used by `desktop_session.py::desktop_interact` (POS: semantic desktop orchestrator)

## Architecture Overview

Detailed design: [DESKTOP_SYSTEM.md](../DESKTOP_SYSTEM.md)
