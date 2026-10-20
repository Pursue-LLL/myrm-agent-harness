# history/

## Overview
history 子模块：jsonl_backend, protocols, tracking_backend, types.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | — | — |
| `jsonl_backend.py` | Core | JSONL-based skill history backend implementation. — JsonlHistoryBackend: JSONL file history backend | ✅ |
| `protocols.py` | Protocol | Skill history backend protocol. — SkillHistoryBackend: Protocol for history storage backends | ✅ |
| `tracking_backend.py` | Core | History tracking skill write backend. — HistoryTrackingSkillWriteBackend: Wrapper service with automatic history tracking | ✅ |
| `types.py` | Types | Skill history types. — SkillHistoryRecord: History record data class; SkillRollbackResult: Rollback result data class | ✅ |
