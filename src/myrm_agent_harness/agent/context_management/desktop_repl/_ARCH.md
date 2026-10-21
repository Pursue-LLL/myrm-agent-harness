# desktop_repl/

## Overview

In-process scripted REPL over a mock desktop SDK that only records actions. It does not drive a real desktop and is not wired to `DesktopSession` or any agent tool.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Exports the REPL engine and its typed contracts. | ✅ |
| `desktop_repl_engine.py` | Core | Executes scripts in a persistent in-process namespace; `DesktopApiSdk` is a mock that only appends to an action log. | ✅ |
| `desktop_repl_types.py` | Types | Typed contracts for REPL commands, execution results, and session snapshots. | ✅ |
