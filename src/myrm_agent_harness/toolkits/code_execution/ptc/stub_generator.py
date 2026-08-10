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


_TYPE_HINTS: dict[str, str] = {
    "array": "list",
    "object": "dict",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
}
# 结构化（array/object）参数需要 json 序列化兼容；数值/布尔参数按 is-not-None 传参。
_STRUCTURED_PARAM_TYPES: frozenset[str] = frozenset({"array", "object"})
_SCALAR_NON_STRING_TYPES: frozenset[str] = frozenset({"integer", "number", "boolean"})


def _extract_json_type(prop: object) -> str:
    """Best-effort extraction of the JSON-schema type of a property.

    Handles both bare ``{"type": "integer"}`` and ``{"anyOf": [{"type": "integer"}, ...]}``
    (the shape pydantic emits for optional fields). Falls back to "string".
    """
    if not isinstance(prop, dict):
        return "string"
    bare = prop.get("type")
    if isinstance(bare, str):
        return bare
    any_of = prop.get("anyOf")
    if isinstance(any_of, list):
        for variant in any_of:
            if isinstance(variant, dict) and variant.get("type") != "null":
                candidate = variant.get("type")
                if isinstance(candidate, str):
                    return candidate
    return "string"


def _extract_params(tool: BaseTool) -> list[tuple[str, str, bool, str]]:
    """Extract (param_name, description, required, json_type) from a tool's schema.

    ``json_type`` is the JSON-schema type ("string" / "array" / "object" / ...);
    array/object params are JSON-serialized before RPC so the generated script can
    pass them as native Python lists/dicts.
    """
    schema = getattr(tool, "args_schema", None)
    if schema is None:
        return []

    try:
        json_schema = schema.model_json_schema()
    except Exception:
        return []

    properties = json_schema.get("properties", {})
    required_set = set(json_schema.get("required", []))
    params: list[tuple[str, str, bool, str]] = []

    for name, prop in properties.items():
        desc = prop.get("description", "") if isinstance(prop, dict) else ""
        is_required = name in required_set
        json_type = _extract_json_type(prop)
        params.append((name, desc, is_required, json_type))

    return params


def _generate_function(tool: BaseTool) -> str:
    """Generate a single tool function stub."""
    params = _extract_params(tool)

    doc_params: list[str] = []

    required_parts: list[str] = []
    optional_parts: list[str] = []

    for name, desc, required, json_type in params:
        if json_type in _TYPE_HINTS:
            hint = _TYPE_HINTS[json_type]
            part = f"{name}: {hint}" if required else f"{name}: {hint} = None"
        else:
            part = f"{name}: str" if required else f"{name}: str = ''"
        if required:
            required_parts.append(part)
        else:
            optional_parts.append(part)
        doc_params.append(f"        {name}: {desc}")

    sig_parts = required_parts + optional_parts

    signature = ", ".join(sig_parts) if sig_parts else ""
    docstring_params = "\n".join(doc_params)

    tool_desc = (tool.description or "").strip().split("\n")[0][:120]

    args_build = "    args = {}\n"
    for name, _, required, json_type in params:
        if json_type in _STRUCTURED_PARAM_TYPES:
            args_build += (
                f"    if isinstance({name}, str):\n"
                f"        {name} = json.loads({name})\n"
            )
            if required:
                args_build += f"    args['{name}'] = {name}\n"
            else:
                args_build += (
                    f"    if {name} is not None:\n        args['{name}'] = {name}\n"
                )
        elif json_type in _SCALAR_NON_STRING_TYPES:
            if required:
                args_build += f"    args['{name}'] = {name}\n"
            else:
                args_build += (
                    f"    if {name} is not None:\n        args['{name}'] = {name}\n"
                )
        else:
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
