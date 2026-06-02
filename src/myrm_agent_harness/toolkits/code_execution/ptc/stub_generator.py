"""PTC dynamic stub generator.

[INPUT]
- langchain_core.tools::BaseTool (POS: Tool definitions to expose as RPC stubs)
- .helpers::HELPERS_SOURCE (POS: Built-in helper functions source)

[OUTPUT]
- generate_stubs: Build myrm_tools.py source code for the child process

[POS]
Generates a Python module (myrm_tools.py) that the LLM-written script imports.
Each enabled tool becomes a synchronous function that does RPC to the parent
server over a UDS/TCP connection. Includes helper utilities and docstrings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.code_execution.ptc.helpers import HELPERS_SOURCE

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

_PREAMBLE = '''\
"""Auto-generated tool stubs for Myrm PTC.

All functions send an RPC to the parent agent process and return the result.
Do NOT modify this file — it is regenerated for each execution.
"""

import json
import os
import shlex
import socket
import struct
import time

_SOCKET_PATH = os.environ["_MYRM_PTC_SOCKET"]
_TIMEOUT = float(os.environ.get("_MYRM_PTC_TIMEOUT", "60"))


def _rpc_call(tool_name: str, args: dict) -> str:
    """Send a single tool call via UDS/TCP and return the result string."""
    payload = json.dumps({"tool": tool_name, "args": args}).encode("utf-8")
    header = struct.pack("!I", len(payload))

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(_TIMEOUT)
    try:
        sock.connect(_SOCKET_PATH)
        sock.sendall(header + payload)

        resp_header = _recv_exact(sock, 4)
        resp_len = struct.unpack("!I", resp_header)[0]
        resp_data = _recv_exact(sock, resp_len)
    finally:
        sock.close()

    resp = json.loads(resp_data)
    if resp.get("error"):
        raise RuntimeError(f"Tool call failed [{tool_name}]: {resp['error']}")
    return resp.get("result", "")


def _recv_exact(sock, n: int) -> bytes:
    """Receive exactly n bytes from socket."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("PTC RPC connection closed unexpectedly")
        buf.extend(chunk)
    return bytes(buf)

'''

_TCP_VARIANT = '''\
# TCP fallback for Windows
_SOCKET_PATH = os.environ.get("_MYRM_PTC_SOCKET")
_TCP_PORT = int(os.environ.get("_MYRM_PTC_PORT", "0"))


def _rpc_call(tool_name: str, args: dict) -> str:
    """Send a single tool call via UDS or TCP and return the result string."""
    payload = json.dumps({"tool": tool_name, "args": args}).encode("utf-8")
    header = struct.pack("!I", len(payload))

    if _SOCKET_PATH:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    else:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    sock.settimeout(_TIMEOUT)
    try:
        if _SOCKET_PATH:
            sock.connect(_SOCKET_PATH)
        else:
            sock.connect(("127.0.0.1", _TCP_PORT))
        sock.sendall(header + payload)

        resp_header = _recv_exact(sock, 4)
        resp_len = struct.unpack("!I", resp_header)[0]
        resp_data = _recv_exact(sock, resp_len)
    finally:
        sock.close()

    resp = json.loads(resp_data)
    if resp.get("error"):
        raise RuntimeError(f"Tool call failed [{tool_name}]: {resp['error']}")
    return resp.get("result", "")

'''


def _extract_params(tool: BaseTool) -> list[tuple[str, str, bool]]:
    """Extract (param_name, description, required) from a tool's schema."""
    schema = getattr(tool, "args_schema", None)
    if schema is None:
        return []

    try:
        json_schema = schema.model_json_schema()
    except Exception:
        return []

    properties = json_schema.get("properties", {})
    required_set = set(json_schema.get("required", []))
    params: list[tuple[str, str, bool]] = []

    for name, prop in properties.items():
        desc = prop.get("description", "")
        is_required = name in required_set
        params.append((name, desc, is_required))

    return params


def _generate_function(tool: BaseTool) -> str:
    """Generate a single tool function stub."""
    params = _extract_params(tool)

    sig_parts: list[str] = []
    doc_params: list[str] = []

    for name, desc, required in params:
        if required:
            sig_parts.insert(0, f"{name}: str")
        else:
            sig_parts.append(f"{name}: str = ''")
        doc_params.append(f"        {name}: {desc}")

    signature = ", ".join(sig_parts) if sig_parts else ""
    docstring_params = "\n".join(doc_params)

    tool_desc = (tool.description or "").strip().split("\n")[0][:120]

    args_build = "    args = {}\n"
    for name, _, required in params:
        if required:
            args_build += f"    args['{name}'] = {name}\n"
        else:
            args_build += f"    if {name}:\n        args['{name}'] = {name}\n"

    func = f'''
def {tool.name}({signature}) -> str:
    """{tool_desc}

    Args:
{docstring_params}
    """
{args_build}    return _rpc_call("{tool.name}", args)

'''
    return func


def generate_stubs(
    tools: list[BaseTool],
    *,
    use_tcp_fallback: bool = False,
) -> str:
    """Generate the complete myrm_tools.py stub module source.

    Args:
        tools: List of enabled tools to expose as stubs
        use_tcp_fallback: Include TCP fallback for Windows compatibility
    """
    parts: list[str] = []

    if use_tcp_fallback:
        preamble_lines = _PREAMBLE.split("\n")
        module_doc_end = next(
            i for i, line in enumerate(preamble_lines) if line.startswith("import json")
        )
        parts.append("\n".join(preamble_lines[:module_doc_end]))
        parts.append(
            "import json\n"
            "import os\n"
            "import shlex\n"
            "import socket\n"
            "import struct\n"
            "import time\n\n"
            '_TIMEOUT = float(os.environ.get("_MYRM_PTC_TIMEOUT", "60"))\n\n'
        )
        parts.append(_TCP_VARIANT)
        parts.append(
            "def _recv_exact(sock, n: int) -> bytes:\n"
            '    """Receive exactly n bytes from socket."""\n'
            "    buf = bytearray()\n"
            "    while len(buf) < n:\n"
            "        chunk = sock.recv(n - len(buf))\n"
            "        if not chunk:\n"
            '            raise ConnectionError("PTC RPC connection closed unexpectedly")\n'
            "        buf.extend(chunk)\n"
            "    return bytes(buf)\n\n"
        )
    else:
        parts.append(_PREAMBLE)

    parts.append(HELPERS_SOURCE)
    parts.append("\n")

    tool_names: list[str] = []
    for tool in tools:
        parts.append(_generate_function(tool))
        tool_names.append(tool.name)

    all_list = ", ".join(f'"{n}"' for n in tool_names)
    parts.append(f"\n__all__ = [{all_list}]\n")

    return "".join(parts)
