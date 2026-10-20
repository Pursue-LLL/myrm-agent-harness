# virtual_room/

## Overview
Virtual Room collaborative workspace & filesystem co-dev package (Item 59).

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Virtual Room collaborative workspace & filesystem co-dev package (Item 59). — Public exports for Tutti-style multi-human multi-agent real-time co-dev suite. | — |
| `agent_borrowing_gateway.py` | Core | Zero-credential cross-user agent capability borrowing gateway (Item 59). — Secure agent proxying without credential exfiltration, enforcing per-grant token budgets | ✅ |
| `fs_lock_engine.py` | Core | Filesystem-level in-flight conflict resolution & lock engine (Item 59). — Lease-based file and line-range locks preventing overlapping concurrent writes | ✅ |
| `room_manager.py` | Core | Virtual Co-Dev Room orchestrator coordinating participants, VFS locks, and relays (Item 59). — Synchronized VirtualRoomState snapshot unifying active participants, active VFS locks, | ✅ |
| `types.py` | Types | Core types for Multi-Human Multi-Agent Collaborative Virtual Room (Item 59). — Strongly-typed models supporting identity-execution-workspace tri-partitioning, | ✅ |
