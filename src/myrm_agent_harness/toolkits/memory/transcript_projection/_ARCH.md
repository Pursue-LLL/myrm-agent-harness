# transcript_projection/

## Overview

SQLite transcript SSOT projection and duplicate adoption disambiguation suite. Provides cold-start session reconstruction without session files, idempotent bootstrapping, repeated content disambiguation by creation time, and fail-closed unstamped handling for twins and missing timestamps.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Facade export for transcript projection and adoption components. | ✅ |
| `models.py` | Types | Domain models for transcript entries, session messages, and adoption decisions. | ✅ |
| `adoption_engine.py` | Core | Disambiguation engine reconciling repeated bodies by created time. | ✅ |
| `projection_store.py` | Storage | SQLite transcript store, session message storage, and idempotent bootstrap. | ✅ |
