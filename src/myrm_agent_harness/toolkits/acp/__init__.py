"""ACP (Agent Client Protocol) integration module.

Provides bidirectional ACP capabilities:
- Server (server/): Bridges IDE clients (Cursor, Zed, VS Code) to the agent system.
- Runtime (runtime/): Connects to external agents via ACP protocol, SDK, or CLI.

Shared infrastructure (root):
- types.py: Core type definitions (RuntimeBackend Protocol, RuntimeEvent, etc.)
- event_bus.py: Unified event bus (publish-subscribe)
- permission.py: Permission management (4 modes)
- health_monitor.py: Backend health monitoring (backoff + restart budget)
- backend_detector.py: CLI backend auto-detection
- auth/: subscription login, credential detection, and credential import for CLI backends


[INPUT]
- server.server::MyrmAcpServer, run_server (POS: ACP protocol layer)
- runtime.pool::RuntimePool (POS: runtime pool management layer)
- types::RuntimeBackend, RuntimeConfig (POS: ACP runtime type definitions)

[OUTPUT]
- MyrmAcpServer: ACP server implementation (lazy import)
- run_server: ACP server launcher (lazy import)
- RuntimePool: unified runtime instance pool (lazy import)
- RuntimeBackend: runtime backend protocol (lazy import)
- RuntimeConfig: runtime configuration model (lazy import)

[POS]
ACP toolkit entry point. Provides lazy-loaded access to server and runtime components
for bidirectional ACP protocol integration.
"""

from __future__ import annotations

__all__ = [
    "MyrmAcpServer",
    "RuntimeBackend",
    "RuntimeConfig",
    "RuntimePool",
    "run_server",
]


def __getattr__(name: str) -> object:
    if name == "MyrmAcpServer":
        from .server.server import MyrmAcpServer

        globals()[name] = MyrmAcpServer
        return MyrmAcpServer

    if name == "run_server":
        from .server.server import run_server

        globals()[name] = run_server
        return run_server

    if name == "RuntimePool":
        from .runtime.pool import RuntimePool

        globals()[name] = RuntimePool
        return RuntimePool

    if name == "RuntimeConfig":
        from .types import RuntimeConfig

        globals()[name] = RuntimeConfig
        return RuntimeConfig

    if name == "RuntimeBackend":
        from .types import RuntimeBackend

        globals()[name] = RuntimeBackend
        return RuntimeBackend

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
