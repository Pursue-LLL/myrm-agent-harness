# element_ref/

## Overview
Shared @dref element reference types and session-scoped registry for semantic desktop control.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| types.py | Core | ElementRef, BBox, SnapshotMeta, SnapshotScope | ✅ |
| registry.py | Core | DRefRegistry session-scoped ref map | ✅ |
| errors.py | Core | DRefStaleError, AXPermissionRequiredError, AXTreeEmptyError | ✅ |
| __init__.py | Package | Public exports | ✅ |

## Dependencies

- Used by `computer_use/desktop_session.py` and `computer_use/perception/`
