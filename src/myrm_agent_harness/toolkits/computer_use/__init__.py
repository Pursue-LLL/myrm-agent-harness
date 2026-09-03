"""Computer Use toolkit — semantic desktop control (SDC).

Public API:
- create_desktop_tools: factory for LangChain tools
- create_desktop_session: session factory
- DesktopSession: semantic desktop session with @dref registry
"""

from myrm_agent_harness.toolkits.computer_use.desktop_agent_tools import create_desktop_tools
from myrm_agent_harness.toolkits.computer_use.desktop_session import (
    DesktopSession,
    create_desktop_session,
)
from myrm_agent_harness.toolkits.computer_use.mcp_server import (
    DesktopMCPServer,
    get_request_desktop_session,
    register_desktop_mcp_tools,
    reset_request_desktop_session,
    set_request_desktop_session,
)
from myrm_agent_harness.toolkits.computer_use.session import (
    ComputerSession,
    create_computer_session,
)

__all__ = [
    "ComputerSession",
    "DesktopMCPServer",
    "DesktopSession",
    "create_computer_session",
    "create_desktop_session",
    "create_desktop_tools",
    "get_request_desktop_session",
    "register_desktop_mcp_tools",
    "reset_request_desktop_session",
    "set_request_desktop_session",
]
