# browser/session_vault/

## Overview

Encrypted session vault for browser authentication persistence. Stores Playwright storageState (cookies + localStorage) encrypted with AES-256-GCM. Never stores plaintext credentials — only post-login session state. O(1) LRU memory cache with TTL and memory limits, singleflight dedup, thread-safe RWLock, and metrics.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public facade: `SessionVault` (save/load/delete/list/cleanup + cache) | ✅ |
| `exceptions.py` | Config | Fine-grained exception hierarchy: `SessionVaultError`/`EncryptionError`/`DecryptionError`/`CorruptedSessionError`/`InvalidDomainError` | ✅ |
| `types.py` | Config | Data types: `SessionEntry`/`SessionSummary`/`VaultMetrics` | ✅ |
| `backends/` | Submodule | Pluggable storage backends (file/cloud/protocol) — see its `_ARCH.md` | ✅ |

## Key Dependencies

- `utils/rwlock` — concurrency control
- `cryptography` — AES-256-GCM (lazy import)
- `orjson` — fast serialization
