# tests/mocks/

## Overview

Shared in-memory test doubles for backend Protocol implementations. Not part of the distributable package.

## File Index

| File | Role | Description |
|------|------|-------------|
| `__init__.py` | Package | Re-exports `InMemorySkillBackend`, `InMemoryStorageBackend` |
| `skill_backend.py` | Mock | In-memory `SkillBackend` for skill unit tests |
| `storage_backend.py` | Mock | In-memory `StorageProvider` for storage unit tests |

## Consumers

- `tests/backends/test_skills.py`
- `tests/toolkits/storage/test_storage.py`
