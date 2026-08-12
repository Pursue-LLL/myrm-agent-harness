# acp/

## Overview
ACP toolkit entry point. Provides lazy-loaded access to server and runtime components

Detailed design: [ACP_SYSTEM.md](ACP_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | ACP toolkit entry point. Provides lazy-loaded access to server and runtime components | ✅ |
| __main__.py | Internal | CLI entry point for the ACP server. | ✅ |
| acp_agent_tools.py | Core | Delegate tasks to external ACP-compatible agents. | ✅ |
| types.py | Config | ACP runtime type definitions layer. Provides all ACP-related core abstractions and data | ✅ |

| Submodule | Description |
|-----------|-------------|
| auth/ | Subscription authentication for external CLI backends. See [auth/_ARCH.md](auth/_ARCH.md). |
| core/ | Shared runtime infrastructure — event bus, permission, health monitor, backend detector. |
| runtime/ | ACP Runtime backends — unified interface for ACP, SDK, and CLI agents. |
| server/ | ACP Server — bridges IDE clients to the agent system via ACP protocol. |
| toolchains/ | Isolated toolchain manager for external CLI agents. See [toolchains/_ARCH.md](toolchains/_ARCH.md). |

## Key Dependencies

- `myrm_agent_harness.core`
- `myrm_agent_harness.utils`
- Optional: `[acp]` → agent-client-protocol (server/, bridge/, event_translator/)
