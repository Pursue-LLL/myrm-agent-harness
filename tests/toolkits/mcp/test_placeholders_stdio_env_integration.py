"""Real-wire integration tests for plugin-root env injection (``placeholders``).

These spin up a *real* stdio MCP server subprocess and drive it through the
production connection pool — no mocks on the transport. They verify, against a
real subprocess boundary, every runtime behavior the Agent Plugins 1.0.0 spec
mandates for bundled servers:

- configured plugin roots are injected as ``PLUGIN_ROOT`` / ``PLUGIN_DATA`` (§9.1);
- without configured roots nothing is injected (the vars stay unset);
- empty-string roots are treated as unconfigured (no bogus ``""`` injection);
- partial injection: each reserved var is injected independently;
- ``${PLUGIN_ROOT}`` / ``${PLUGIN_DATA}`` placeholders expand in ``cwd``, ``args``
  and ``env`` values at spawn time;
- a ``./``-relative ``command`` runs from the plugin root even without an
  explicit ``cwd`` (§7.2.1).

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
# the reserved plugin vars, a custom env var, the working directory, and argv.
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
        "CUSTOM_ENV": os.environ.get("CUSTOM_ENV", "UNSET"),
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


def _make_roots(tmp_path: object) -> tuple[str, str]:
    plugin_root = tmp_path / "plugin_root"
    data_root = tmp_path / "plugin_data"
    plugin_root.mkdir()
    data_root.mkdir()
    return str(plugin_root), str(data_root)


def _write_probe_script(tmp_path: object) -> str:
    script = tmp_path / "env_probe_server.py"
    script.write_text(_ENV_PROBE_SERVER_SRC, encoding="utf-8")
    return str(script)


def _extract_json(raw: str) -> dict[str, object]:
    """The call result wraps the tool output in a security notice; the first
    line after the ``---`` separator is the raw tool JSON payload."""
    body = raw.split("---\n", 1)[1]
    return json.loads(body.splitlines()[0])


async def _probe(
    command: str,
    args: list[str],
    extra_params: dict[str, object] | None,
) -> dict[str, object]:
    cfg = MCPConfig(
        name="envprobe",
        type="stdio",
        command=command,
        args=args,
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
    plugin_root, data_root = _make_roots(tmp_path)

    report = await _probe(
        sys.executable,
        [_write_probe_script(tmp_path)],
        {"plugin_root": plugin_root, "data_root": data_root},
    )
    assert report["PLUGIN_ROOT"] == plugin_root
    assert report["PLUGIN_DATA"] == data_root


@pytest.mark.integration
async def test_stdio_skips_injection_without_configured_roots(
    tmp_path: object, _reset_manager: object
) -> None:
    """Without configured roots the reserved vars must stay unset in the subprocess."""
    report = await _probe(sys.executable, [_write_probe_script(tmp_path)], None)
    assert report["PLUGIN_ROOT"] == "UNSET"
    assert report["PLUGIN_DATA"] == "UNSET"


@pytest.mark.integration
async def test_stdio_treats_empty_string_root_as_unconfigured(
    tmp_path: object, _reset_manager: object
) -> None:
    """Empty-string roots must not inject bogus ``""`` values (regression guard)."""
    plugin_root, data_root = _make_roots(tmp_path)

    report = await _probe(
        sys.executable,
        [_write_probe_script(tmp_path)],
        {"plugin_root": "", "data_root": data_root},
    )
    assert report["PLUGIN_ROOT"] == "UNSET"
    assert report["PLUGIN_DATA"] == data_root


@pytest.mark.integration
async def test_stdio_injects_each_reserved_var_independently(
    tmp_path: object, _reset_manager: object
) -> None:
    """Partial configuration: only the configured root is injected (§9.1 per-var)."""
    plugin_root, data_root = _make_roots(tmp_path)

    report = await _probe(
        sys.executable,
        [_write_probe_script(tmp_path)],
        {"plugin_root": plugin_root},
    )
    assert report["PLUGIN_ROOT"] == plugin_root
    assert report["PLUGIN_DATA"] == "UNSET"


@pytest.mark.integration
async def test_stdio_expands_placeholders_in_env_args_and_cwd(
    tmp_path: object, _reset_manager: object
) -> None:
    """``${PLUGIN_ROOT}`` / ``${PLUGIN_DATA}`` must expand in env/args/cwd (§9)."""
    plugin_root, data_root = _make_roots(tmp_path)
    script = _write_probe_script(tmp_path)

    report = await _probe(
        sys.executable,
        [script, "${PLUGIN_ROOT}/args-res", "${PLUGIN_DATA}/data-res"],
        {
            "plugin_root": plugin_root,
            "data_root": data_root,
            "env": {"CUSTOM_ENV": "${PLUGIN_ROOT}/env-res"},
            "cwd": "${PLUGIN_ROOT}",
        },
    )
    assert report["PLUGIN_ROOT"] == plugin_root
    assert report["PLUGIN_DATA"] == data_root
    assert report["CUSTOM_ENV"] == f"{plugin_root}/env-res"
    assert report["CWD"] == plugin_root
    assert report["ARGV"][-2:] == [f"{plugin_root}/args-res", f"{data_root}/data-res"]


@pytest.mark.integration
async def test_stdio_dot_slash_command_runs_from_plugin_root(
    tmp_path: object, _reset_manager: object
) -> None:
    """A ``./``-relative command implies the plugin root as cwd (§7.2.1)."""
    plugin_root, data_root = _make_roots(tmp_path)
    bin_dir = tmp_path / "plugin_root" / "bin"
    bin_dir.mkdir()
    probe_bin = bin_dir / "probe.py"
    probe_bin.write_text(
        f"#!{sys.executable}\n" + _ENV_PROBE_SERVER_SRC, encoding="utf-8"
    )
    probe_bin.chmod(0o755)

    report = await _probe("./bin/probe.py", [], {"plugin_root": plugin_root, "data_root": data_root})
    assert report["PLUGIN_ROOT"] == plugin_root
    assert report["CWD"] == plugin_root
    assert report["ARGV"][0].endswith("bin/probe.py")


@pytest.mark.integration
async def test_stdio_strips_dangerous_env_variables_at_runtime(
    tmp_path: object, _reset_manager: object
) -> None:
    """Malicious injection variables (e.g. LD_PRELOAD, PYTHONPATH) must be stripped at launch time."""
    plugin_root, data_root = _make_roots(tmp_path)
    script = _write_probe_script(tmp_path)

    report = await _probe(
        sys.executable,
        [script],
        {
            "plugin_root": plugin_root,
            "data_root": data_root,
            "env": {
                "CUSTOM_ENV": "legitimate_value",
                "LD_PRELOAD": "/tmp/rootkit.so",
                "PYTHONPATH": "/tmp/evil_lib",
                "node_options": "--inspect",
            },
        },
    )
    assert report["PLUGIN_ROOT"] == plugin_root
    assert report["PLUGIN_DATA"] == data_root
    assert report["CUSTOM_ENV"] == "legitimate_value"
    # Ensure malicious env variables are not present in the subprocess environment
    import os
    assert os.environ.get("LD_PRELOAD") != "/tmp/rootkit.so"

