# local/

## Overview
Local code executor module. Executes Python code and Bash commands on the
host machine using subprocesses, persistent sessions, and OS-level sandboxing.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports `LocalExecutor`. | — |
| executor.py | Core | Orchestrator: Python/Bash execution, session lifecycle, workspace binding. | ✅ |
| _file_ops.py | Core | Native file I/O (read/write/grep/glob) via pathlib. Every mutation passes `_guard_write`, which refuses the executor's configured read-only roots and, through the shared `core.security.path` rules, credential paths, persona instruction files, read-only evidence directories and the active Goal's protected paths — so a sandbox write is refused exactly when the file tools or the shell pre-flight would refuse it. Reads of those paths stay open. write/append/delete fire `trigger_destructive_action_hook` (carries `session_id` for turn/chat binding). | ✅ |
| _python_subprocess.py | Helper | Python script subprocess: sandbox wrapping, readonly_workspace context passthrough, env, timeout, output parsing. | ✅ |
| _background_spawn.py | Helper | Background process spawning with sandbox, env isolation, process groups; **PTY-first on POSIX (non-sandbox) with PIPE fallback** via `_background_pty_spawn.py`. | ✅ |
| _background_pty_spawn.py | Helper | POSIX PTY master/slave spawn adapter (merged stdout/stderr); skipped under bwrap or on Windows. | ✅ |
