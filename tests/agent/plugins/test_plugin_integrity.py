"""Tests for PluginPackagingIntegrityGuard in Harness.

Validates that referenced build artifacts / entrypoint scripts in stdio MCP servers
are verified during package parsing, generating diagnostics and filtering broken servers
to prevent runtime Agent subprocess crashes.
"""

from __future__ import annotations

import io
import zipfile

from myrm_agent_harness.agent.plugins.integrity import (
    extract_server_entrypoint_path,
    extract_server_raw_entrypoint,
    filter_valid_servers,
    infer_server_capabilities,
    normalize_package_path,
    verify_mcp_server_artifacts,
    verify_plugin_capability_diff,
)
from myrm_agent_harness.agent.plugins.models import (
    PluginCapabilityTier,
    PluginDiagnosticLevel,
    PluginMcpServer,
)

PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"


def _build_zip(entries: dict[str, str], top_dir: str = "test-plugin") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel_path, content in entries.items():
            zf.writestr(f"{top_dir}/{rel_path}", content)
    return buf.getvalue()


class TestPathNormalization:
    def test_normalize_package_path_basic(self) -> None:
        assert normalize_package_path("./dist/index.js") == "dist/index.js"
        assert normalize_package_path("dist/index.js") == "dist/index.js"
        assert normalize_package_path(r".\dist\index.js") == "dist/index.js"
        assert normalize_package_path("  ./bin/cli.mjs  ") == "bin/cli.mjs"
        assert normalize_package_path("${PLUGIN_ROOT}/out/run.js") == "out/run.js"


class TestExtractServerEntrypointPath:
    def test_non_stdio_returns_none(self) -> None:
        server = PluginMcpServer(
            name="remote",
            server_type="streamable_http",
            command=None,
            args=None,
            url="https://example.com/mcp",
            headers=None,
            cwd=None,
        )
        assert extract_server_entrypoint_path(server) is None
        assert extract_server_raw_entrypoint(server) is None

    def test_stdio_relative_command(self) -> None:
        server = PluginMcpServer(
            name="local-script",
            server_type="stdio",
            command="./bin/server.sh",
            args=[],
            url=None,
            headers=None,
            cwd=None,
        )
        assert extract_server_entrypoint_path(server) == "bin/server.sh"
        assert extract_server_raw_entrypoint(server) == "./bin/server.sh"

    def test_stdio_node_with_dist_arg(self) -> None:
        server = PluginMcpServer(
            name="node-mcp",
            server_type="stdio",
            command="node",
            args=["./dist/index.js", "--port", "8000"],
            url=None,
            headers=None,
            cwd=None,
        )
        assert extract_server_entrypoint_path(server) == "dist/index.js"
        assert extract_server_raw_entrypoint(server) == "./dist/index.js"

    def test_stdio_python_with_script_arg(self) -> None:
        server = PluginMcpServer(
            name="py-mcp",
            server_type="stdio",
            command="python3",
            args=["-u", "./src/mcp_server.py"],
            url=None,
            headers=None,
            cwd=None,
        )
        assert extract_server_entrypoint_path(server) == "src/mcp_server.py"
        assert extract_server_raw_entrypoint(server) == "./src/mcp_server.py"

    def test_stdio_system_binary_no_script_arg(self) -> None:
        server = PluginMcpServer(
            name="system-tool",
            server_type="stdio",
            command="docker",
            args=["run", "-i", "my-container"],
            url=None,
            headers=None,
            cwd=None,
        )
        assert extract_server_entrypoint_path(server) is None


class TestVerifyMcpServerArtifacts:
    def test_missing_node_dist_with_ts_sources(self) -> None:
        server = PluginMcpServer(
            name="unbuilt-ts",
            server_type="stdio",
            command="node",
            args=["./dist/index.js"],
            url=None,
            headers=None,
            cwd=None,
        )
        files = {"src/index.ts", "package.json"}
        is_valid, missing_path, reason = verify_mcp_server_artifacts(
            server, files, has_ts_sources=True
        )
        assert is_valid is False
        assert missing_path == "dist/index.js"
        assert reason is not None
        assert "npm run build" in reason

    def test_existing_bundled_script(self) -> None:
        server = PluginMcpServer(
            name="ready-server",
            server_type="stdio",
            command="./server.py",
            args=[],
            url=None,
            headers=None,
            cwd=None,
        )
        files = {"server.py", "plugin.json"}
        is_valid, missing_path, reason = verify_mcp_server_artifacts(server, files)
        assert is_valid is True
        assert missing_path is None
        assert reason is None


class TestFilterAndVerifyPluginPackagingIntegrity:
    def test_filter_valid_servers(self) -> None:
        s1 = PluginMcpServer("valid", "stdio", "./run.sh", [], None, None, None)
        s2 = PluginMcpServer("broken", "stdio", "node", ["./dist/index.js"], None, None, None)
        files = {"run.sh"}

        diags: list = []
        valid = filter_valid_servers([s1, s2], files, diags)
        assert len(valid) == 1
        assert valid[0].name == "valid"
        assert len(diags) == 1
        assert diags[0].code == "mcp_missing_artifact"
        assert "broken" in diags[0].component


class TestCapabilityInferenceAndDiff:
    def test_infer_server_capabilities_stdio(self) -> None:
        server = PluginMcpServer("local", "stdio", "./run.sh", [], None, None, None)
        caps = infer_server_capabilities(server)
        assert PluginCapabilityTier.SHELL_EXEC in caps
        assert PluginCapabilityTier.FS_READ in caps
        assert PluginCapabilityTier.FS_WRITE in caps

    def test_infer_server_capabilities_remote(self) -> None:
        server = PluginMcpServer("remote", "streamable_http", None, None, "https://api.example.com", None, None)
        caps = infer_server_capabilities(server)
        assert caps == (PluginCapabilityTier.NETWORK,)

    def test_infer_server_capabilities_destructive_command(self) -> None:
        server = PluginMcpServer("danger", "stdio", "bash", ["-c", "rm -rf /tmp/data"], None, None, None)
        caps = infer_server_capabilities(server)
        assert PluginCapabilityTier.DESTRUCTIVE in caps

    def test_verify_capability_diff_clean(self) -> None:
        server = PluginMcpServer(
            "net",
            "streamable_http",
            None,
            None,
            "https://api.example.com",
            None,
            None,
            capabilities=(PluginCapabilityTier.NETWORK,),
        )
        diags = verify_plugin_capability_diff([PluginCapabilityTier.NETWORK], [server])
        assert diags == []

    def test_verify_capability_diff_undeclared_high_risk(self) -> None:
        server = PluginMcpServer(
            "shell",
            "stdio",
            "./run.sh",
            [],
            None,
            None,
            None,
            capabilities=(PluginCapabilityTier.SHELL_EXEC,),
        )
        # Declared only read_only, but server needs shell_exec
        diags = verify_plugin_capability_diff([PluginCapabilityTier.READ_ONLY], [server])
        assert len(diags) == 1
        assert diags[0].code == "capability_undeclared_privilege"
        assert diags[0].level == PluginDiagnosticLevel.ERROR
        assert "shell_exec" in diags[0].message

