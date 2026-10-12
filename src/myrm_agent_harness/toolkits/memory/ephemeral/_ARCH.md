# ephemeral/

## Overview

Subagent memory isolation strategies. `EphemeralMemoryManager` reads from the parent and writes to a local dict; `ReadOnlyMemoryView` reads from the parent and rejects every write. Import them from `toolkits.memory.ephemeral`.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Ephemeral and read-only memory managers for subagent isolation. | ✅ |
| dict_backed_manager.py | Core | Dict-backed ephemeral memory manager: reads span the parent's persistent memory and a local dict, writes stay in the dict. | ✅ |
| read_only_view.py | Core | Read-only proxy over a parent MemoryManager: reads delegate to the parent, writes raise PermissionError. | ✅ |
