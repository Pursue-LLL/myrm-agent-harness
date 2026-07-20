# runtime/

## Overview
ACP Runtime backends — unified interface for ACP, SDK, and CLI agents.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | ACP Runtime backends — unified interface for ACP, SDK, and CLI agents. | — |
| _base.py | Internal | Base class for RuntimeBackend implementations. | ✅ |
| _parser.py | Internal | Shared NDJSON event parsers for CLI and SDK runtimes. | ✅ |
| _spawn_hints.py | Internal | Bare CLI spawn failure hints for CliRuntime error messages. | ✅ |
| acp_callback.py | Core | ACP callback handler for the AcpRuntime backend. | ✅ |
| acp_runtime.py | Core | ACP protocol runtime backend. | ✅ |
| cli_runtime.py | Core | CLI runtime backend — spawns a CLI agent process and parses NDJSON output. | ✅ |
| pool.py | Core | Runtime pool management layer. Provides multi-backend unified management, concurrency control, | ✅ |
| sdk_runtime.py | Core | SDK runtime backend — direct integration with Claude Agent SDK. | ✅ |
