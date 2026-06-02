# local/

## Overview
Local code executor module. Executes Python code and Bash commands on the
host machine using subprocesses, persistent sessions, and OS-level sandboxing.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports `LocalExecutor`. | — |
| executor.py | Core | Orchestrator: Python/Bash execution, session lifecycle, workspace binding. | ✅ |
| _file_ops.py | Mixin | Native file I/O (read/write/grep/glob) via pathlib with read-only guard. | ✅ |
| _python_subprocess.py | Helper | Python script subprocess: sandbox wrapping, env, timeout, output parsing. | ✅ |
| _background_spawn.py | Helper | Background process spawning with sandbox, env isolation, process groups. | ✅ |
