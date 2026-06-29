# computer_use/dref/

## Overview

Internal @dref element reference types and session-scoped registry for semantic desktop control.
Owned by `computer_use/` — not a standalone toolkit.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| types.py | Core | ElementRef, BBox, SnapshotMeta, SnapshotScope | ✅ |
| registry.py | Core | DRefRegistry session-scoped ref map | ✅ |
| errors.py | Core | DRefStaleError, AXPermissionRequiredError, AXTreeEmptyError | ✅ |
| __init__.py | Package | Public exports | ✅ |

## Consumers

- `computer_use/desktop_session.py`
- `computer_use/perception/*`
- `computer_use/execution/healer.py`
