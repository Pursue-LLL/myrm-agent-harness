"""ACP Server — bridges IDE clients to the agent system via ACP protocol."""

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
