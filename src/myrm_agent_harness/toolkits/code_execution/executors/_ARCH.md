# executors/

## Overview
Executors module for Agent-in-Sandbox mode.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Executors module for Agent-in-Sandbox mode. | — |
| base.py | Core | Code executor base classes, including default file I/O and atomic replace file-write contract. | ✅ |
| models.py | Core | Data models for code execution. | ✅ |
| readonly_proxy.py | Core | Read-only executor proxy for zero-copy isolation with OS-level fallback security. | ✅ |
| test_executor.py | Core | Subprocess-based test execution for skill evolution TDE. | ✅ |

| Submodule | Description |
|-----------|-------------|
| common/ | Common executor components. |
| local/ | Local executor module with native pathlib I/O and atomic write overrides. |

## Key Dependencies

- `core`
