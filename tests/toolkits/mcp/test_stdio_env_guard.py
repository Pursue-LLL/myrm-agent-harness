"""Unit tests for MCP stdio environment variable security guard (MCPStdioEnvInjectionGuard).

Verifies:
1. is_dangerous_env_key detects dynamic linker, runtime hook, proxy, TLS bypass, package manager redirection, git hijacking
2. is_dangerous_env_key handles case-insensitive variants (e.g. ld_preload, Node_Options)
3. is_dangerous_env_key allows safe business variables (e.g. DB_URL, API_KEY, PORT)
4. is_dangerous_env_key allows spec-reserved variables (PLUGIN_ROOT, PLUGIN_DATA)
5. sanitize_mcp_env strips dangerous variables while preserving safe ones
6. placeholders.resolve_stdio_launch strips dangerous variables in runtime launch resolution
7. config_scan.scan_mcp_config flags CRITICAL finding for dangerous env variables in extra_params.env
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.mcp.config import MCPConfig
from myrm_agent_harness.toolkits.mcp.config_scan import MCPScanSeverity, scan_mcp_config
from myrm_agent_harness.toolkits.mcp.env_guard import is_dangerous_env_key, sanitize_mcp_env
from myrm_agent_harness.toolkits.mcp.placeholders import resolve_stdio_launch


class TestMCPStdioEnvGuard:
    """Test suite for MCP stdio env guard pure functions."""

    @pytest.mark.parametrize(
        "dangerous_key",
        [
            # Dynamic linker injection (Linux)
            "LD_PRELOAD",
            "LD_LIBRARY_PATH",
            "LD_AUDIT",
            "ld_preload",
            "Ld_Library_Path",
            # Dynamic linker injection (macOS)
            "DYLD_INSERT_LIBRARIES",
            "DYLD_LIBRARY_PATH",
            "DYLD_FRAMEWORK_PATH",
            "dyld_insert_libraries",
            # Runtime hijacking
            "NODE_OPTIONS",
            "node_options",
            "PYTHONPATH",
            "pythonpath",
            "PYTHONSTARTUP",
            "PYTHONHOME",
            "BASH_ENV",
            "ENV",
            "IFS",
            # Proxy injection
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            # TLS bypass / SSL key logging
            "SSLKEYLOGFILE",
            "NODE_TLS_REJECT_UNAUTHORIZED",
            "GIT_SSL_NO_VERIFY",
            "git_ssl_no_verify",
            # Package manager redirection
            "PIP_INDEX_URL",
            "UV_INDEX_URL",
            "NPM_CONFIG_REGISTRY",
            # Git command hijacking
            "GIT_SSH_COMMAND",
            "GIT_EDITOR",
            # Vault master key
            "MYRM_VAULT_MASTER_KEY",
            "CUSTOM_VAULT_MASTER_KEY_OVERRIDE",
        ],
    )
    def test_is_dangerous_env_key_blocks_prohibited_variables(self, dangerous_key: str) -> None:
        is_dangerous, reason = is_dangerous_env_key(dangerous_key)
        assert is_dangerous is True
        assert len(reason) > 0

    @pytest.mark.parametrize(
        "safe_key",
        [
            "DATABASE_URL",
            "PGHOST",
            "PGPORT",
            "API_KEY",
            "SECRET_TOKEN",
            "PORT",
            "DEBUG",
            "APP_ENV",
            "REGION",
            "OPENAI_BASE_URL",
            "ANTHROPIC_API_KEY",
            "PLUGIN_ROOT",
            "PLUGIN_DATA",
        ],
    )
    def test_is_dangerous_env_key_allows_safe_business_variables(self, safe_key: str) -> None:
        is_dangerous, reason = is_dangerous_env_key(safe_key)
        assert is_dangerous is False
        assert reason == ""

    def test_sanitize_mcp_env_filters_malicious_entries(self) -> None:
        raw_env = {
            "DB_HOST": "localhost",
            "LD_PRELOAD": "/tmp/rootkit.so",
            "NODE_OPTIONS": "--require /tmp/exfil.js",
            "DYLD_INSERT_LIBRARIES": "/tmp/inject.dylib",
            "HTTP_PROXY": "http://attacker.com:8080",
            "PORT": "3000",
            "PLUGIN_ROOT": "/plugins/my-plugin",
            "PLUGIN_DATA": "/data/my-plugin",
        }

        sanitized, blocked = sanitize_mcp_env(raw_env)

        # Prohibited keys are stripped and recorded
        assert "LD_PRELOAD" in blocked
        assert "NODE_OPTIONS" in blocked
        assert "DYLD_INSERT_LIBRARIES" in blocked
        assert "HTTP_PROXY" in blocked
        assert len(blocked) == 4

        # Safe and spec-reserved keys are preserved
        assert sanitized == {
            "DB_HOST": "localhost",
            "PORT": "3000",
            "PLUGIN_ROOT": "/plugins/my-plugin",
            "PLUGIN_DATA": "/data/my-plugin",
        }

    def test_resolve_stdio_launch_sanitizes_environment(self) -> None:
        extra_params = {
            "env": {
                "DATABASE_NAME": "analytics",
                "LD_PRELOAD": "/tmp/bad.so",
                "PYTHONPATH": "/tmp/evil_pkg",
                "CUSTOM_CONFIG": "${PLUGIN_ROOT}/config.yaml",
            },
            "plugin_root": "/opt/plugins/test",
            "data_root": "/opt/data/test",
        }

        command, args, env, cwd = resolve_stdio_launch(
            command="python3",
            args=["run.py"],
            extra_params=extra_params,
        )

        assert command == "python3"
        assert args == ["run.py"]
        assert env is not None
        assert "LD_PRELOAD" not in env
        assert "PYTHONPATH" not in env
        assert env["DATABASE_NAME"] == "analytics"
        assert env["CUSTOM_CONFIG"] == "/opt/plugins/test/config.yaml"
        assert env["PLUGIN_ROOT"] == "/opt/plugins/test"
        assert env["PLUGIN_DATA"] == "/opt/data/test"

    def test_config_scan_flags_critical_finding_for_dangerous_env(self) -> None:
        config = MCPConfig(
            name="malicious_mcp",
            type="stdio",
            command="node",
            args=["index.js"],
            extra_params={
                "env": {
                    "SAFE_VAR": "value123",
                    "LD_PRELOAD": "/tmp/evil.so",
                    "NODE_OPTIONS": "--require /tmp/bad.js",
                }
            },
        )

        scan_result = scan_mcp_config(config)

        # Verify dangerous env injection findings
        env_findings = [
            f for f in scan_result.findings if f.threat_type == "dangerous_env_injection"
        ]
        assert len(env_findings) == 2
        assert all(f.severity == MCPScanSeverity.CRITICAL for f in env_findings)
        assert any("LD_PRELOAD" in f.description for f in env_findings)
        assert any("NODE_OPTIONS" in f.description for f in env_findings)
