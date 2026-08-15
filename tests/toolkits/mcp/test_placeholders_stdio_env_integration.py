"""Real-wire integration tests for plugin-root env injection (``placeholders``).

These spin up a *real* stdio MCP server subprocess and drive it through the
production connection pool — no mocks on the transport. They verify that the
``PLUGIN_ROOT`` / ``PLUGIN_DATA`` environment variables mandated by Agent
Plugins 1.0.0 §9.1 are actually visible inside the plugin subprocess:

- configured plugin roots are injected with the persisted absolute paths;
- without configured roots nothing is injected (the vars stay unset);
- ``cwd``/``args`` placeholder expansion takes effect on the real subprocess.

This is the wire-level complement to the pure unit tests in
``test_placeholders.py``.
"""

from __future__ import annotations

import json
import sys

import pytest

from myrm_agent_harness.toolkits.mcp.config import MCPConfig
from myrm_agent_harness.toolkits.mcp.connection_manager import MCPConnectionManager

# A real MCP server that reports the runtime environment it actually received:
# the reserved plugin vars, the working directory, and its argv.
_ENV_PROBE_SERVER_SRC = """
import json
import os
import sys

from mcp.server.mcpserver import MCPServer

server = MCPServer("env-probe")


@server.tool()
def probe() -> str:
    return json.dumps({
        "PLUGIN_ROOT": os.environ.get("PLUGIN_ROOT", "UNSET"),
        "PLUGIN_DATA": os.environ.get("PLUGIN_DATA", "UNSET"),
        "CWD": os.getcwd(),
        "ARGV": list(sys.argv),
    })


if __name__ == "__main__":
    server.run(transport="stdio")
"""


@pytest.fixture
def _reset_manager() -> object:
    MCPConnectionManager._instance = None
    yield
    MCPConnectionManager._instance = None


def _write_probe_script(tmp_path: object) -> str:
    script = tmp_path / "env_probe_server.py"
    script.write_text(_ENV_PROBE_SERVER_SRC, encoding="utf-8")
    return str(script)


def _extract_json(raw: str) -> dict[str, object]:
    """The call result wraps the tool output in a security notice; the first
    line after the ``---`` separator is the raw tool JSON payload."""
    body = raw.split("---\n", 1)[1]
    return json.loads(body.splitlines()[0])


async def _probe(script: str, extra_params: dict[str, object] | None) -> dict[str, object]:
    cfg = MCPConfig(
        name="envprobe",
        type="stdio",
        command=sys.executable,
        args=[script],
        description="env probe",
        extra_params=extra_params,
        connect_timeout=30.0,
    )
    manager = await MCPConnectionManager.get_instance()
    try:
        conn = await manager.get_connection([cfg])
        return _extract_json(str(await conn.call("envprobe", "probe", {})))
    finally:
        await manager.stop()


@pytest.mark.integration
async def test_stdio_injects_plugin_roots_into_subprocess_env(
    tmp_path: object, _reset_manager: object
) -> None:
    """Configured plugin roots must reach the subprocess as reserved vars (§9.1)."""
    script = _write_probe_script(tmp_path)
    plugin_root = tmp_path / "plugin_root"
    data_root = tmp_path / "plugin_data"
    plugin_root.mkdir()
    data_root.mkdir()

    report = await _probe(
        script,
        {"plugin_root": str(plugin_root), "data_root": str(data_root)},
    )
    assert report["PLUGIN_ROOT"] == str(plugin_root)
    assert report["PLUGIN_DATA"] == str(data_root)


@pytest.mark.integration
async def test_stdio_skips_injection_without_configured_roots(
    tmp_path: object, _reset_manager: object
) -> None:
    """Without configured roots the reserved vars must stay unset in the subprocess."""
    script = _write_probe_script(tmp_path)

    report = await _probe(script, None)
    assert report["PLUGIN_ROOT"] == "UNSET"
    assert report["PLUGIN_DATA"] == "UNSET"


@pytest.mark.integration
async def test_stdio_expands_cwd_placeholder_on_real_subprocess(
    tmp_path: object, _reset_manager: object
) -> None:
    """``cwd: ${PLUGIN_ROOT}`` must resolve to the persisted root at spawn time."""
    script = _write_probe_script(tmp_path)
    plugin_root = tmp_path / "plugin_root"
    data_root = tmp_path / "plugin_data"
    plugin_root.mkdir()
    data_root.mkdir()

    report = await _probe(
        script,
        {
            "plugin_root": str(plugin_root),
            "data_root": str(data_root),
            "cwd": "${PLUGIN_ROOT}",
        },
    )
    assert report["PLUGIN_ROOT"] == str(plugin_root)
    assert report["CWD"] == str(plugin_root)
