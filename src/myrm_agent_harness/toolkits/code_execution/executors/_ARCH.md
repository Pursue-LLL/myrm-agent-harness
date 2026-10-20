# executors/

## Overview
Executors module for Agent-in-Sandbox mode.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Executors module for Agent-in-Sandbox mode. | — |
| base.py | Core | Code executor base classes, including default file I/O and atomic replace file-write contract. | ✅ |
| execution_evidence.py | Core | Per-scope record that a process was actually launched; the verifier's PASS gate reads it. | ✅ |
| models.py | Core | Data models for code execution. | ✅ |
| shell_file_transfer.py | Core | Chunked byte-exact file read (hex via `dd` + `od`) and write (base64) for shell-only executors, immune to stdout truncation and scrubbing. | ✅ |
| test_executor.py | Core | Subprocess-based test execution for skill evolution TDE. | ✅ |

| Submodule | Description |
|-----------|-------------|
| common/ | Common executor components. |
| local/ | Local executor module with native pathlib I/O and atomic write overrides. |
| `readonly_proxy.py` | Core | Read-only executor proxy for Adversarial Sandbox Verifier. — ReadonlyExecutorProxy: Executor middleware that enforces read-only access and tracks execution. | ✅ |

## Key Dependencies

- `core`
