"""IPC socket path and permission policy shared by the MCP transport.

[OUTPUT]
- default_ipc_socket_path: Per-process socket path inside a private directory.
- SOCKET_DIR_MODE / SOCKET_FILE_MODE: Owner-only modes for the dir and socket.

[POS]
Leaf module with no project imports, living in ``core/`` because two layers share it:
the code-execution config (toolkits) and the MCP IPC server (agent). Placing it under
``agent/`` would force toolkits to import the agent layer.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

SOCKET_DIR_MODE = 0o700
SOCKET_FILE_MODE = 0o600


def default_ipc_socket_path() -> str:
    """Return the per-process IPC socket path.

    A shared, predictable ``/tmp/<name>/mcp.sock`` lets another local user
    pre-create the socket or connect to it. Keying the directory by PID and
    keeping it owner-only closes that hole.
    """
    return str(Path(tempfile.gettempdir()) / f"myrm-agent-mcp-{os.getpid()}" / "mcp.sock")


__all__ = ["SOCKET_DIR_MODE", "SOCKET_FILE_MODE", "default_ipc_socket_path"]
