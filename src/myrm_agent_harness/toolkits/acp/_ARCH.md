# acp/

## Overview
ACP toolkit entry point. Provides lazy-loaded access to server and runtime components

Detailed design: [ACP_DESIGN.md](ACP_DESIGN.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | ACP toolkit entry point. Provides lazy-loaded access to server and runtime components | ✅ |
| __main__.py | Internal | CLI entry point for the ACP server. | ✅ |
| acp_agent_tools.py | Core | Delegate tasks to external ACP-compatible agents. | ✅ |
| backend_detector.py | Core | Automatic detection of CLI agent backends. | ✅ |
| event_bus.py | Core | ACP event bus layer. Provides decoupled event dispatch mechanism for the Runtime system with session | ✅ |
| health_monitor.py | Core | Health monitor for RuntimeBackend instances. | ✅ |
| permission.py | Core | ACP permission management layer. Provides framework-level permission control with safe/ask/allow_all | ✅ |
| types.py | Config | ACP runtime type definitions layer. Provides all ACP-related core abstractions and data | ✅ |

| Submodule | Description |
|-----------|-------------|
| runtime/ | ACP Runtime backends — unified interface for ACP, SDK, and CLI agents. |
| server/ | ACP Server — bridges IDE clients to the agent system via ACP protocol. |
| toolchains/ | Isolated toolchain manager for external CLI agents. See [toolchains/_ARCH.md](toolchains/_ARCH.md). |

## Key Dependencies

- `core`
- `utils`
