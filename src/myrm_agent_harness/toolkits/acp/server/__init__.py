"""ACP Server — bridges IDE clients to the agent system via ACP protocol.

[INPUT]
- toolkits.acp.server.server::MyrmAcpServer, run_server (POS: ACP protocol layer) [lazy]
- toolkits.acp.server.bridge::AgentBridge, AgentFactory (POS: ACP session-to-agent mapping layer) [lazy]

[OUTPUT]
- MyrmAcpServer: lazy-imported ACP server implementation
- run_server: lazy-imported ACP server launcher
- AgentBridge: lazy-imported session-to-agent bridge
- AgentFactory: lazy-imported agent factory

[POS]
ACP server direction — IDE clients talk to the hosted agent system over ACP.
"""

from __future__ import annotations

__all__ = [
    "AgentBridge",
    "AgentFactory",
    "MyrmAcpServer",
    "run_server",
]


def __getattr__(name: str) -> object:
    if name == "MyrmAcpServer":
        from .server import MyrmAcpServer

        globals()[name] = MyrmAcpServer
        return MyrmAcpServer

    if name == "run_server":
        from .server import run_server

        globals()[name] = run_server
        return run_server

    if name == "AgentBridge":
        from .bridge import AgentBridge

        globals()[name] = AgentBridge
        return AgentBridge

    if name == "AgentFactory":
        from .bridge import AgentFactory

        globals()[name] = AgentFactory
        return AgentFactory

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
