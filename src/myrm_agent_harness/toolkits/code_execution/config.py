"""Code execution configuration.

Agent-in-Sandbox mode: Agent runs in a container, code executes locally (LOCAL mode).
Container lifecycle is managed by myrm-control-plane; harness handles in-container execution.

Network configuration:
- CODE_EXECUTION_ALLOW_NETWORK: allow network access (default false)
- CODE_EXECUTION_ALLOWED_HOSTS: comma-separated domain allowlist


[INPUT]
(none — leaf configuration module, no internal dependencies)

[OUTPUT]
- NetworkConfig: network access configuration model
- ExecutionMode: execution mode enum (LOCAL)
- LocalExecutionConfig: local executor settings
- MCPIPCConfig: MCP IPC communication settings
- ExecutionConfig: top-level execution configuration
- get_execution_config(): global config singleton accessor

[POS]
Code execution configuration layer. Defines execution modes, network policies, and runtime settings
for the Agent-in-Sandbox architecture.
"""

from enum import StrEnum

from pydantic import BaseModel, Field

DEFAULT_ALLOWED_HOSTS: frozenset[str] = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "storage",
        "object-storage",
        "pypi.org",
        "files.pythonhosted.org",
        "registry.npmjs.org",
    }
)


class NetworkConfig(BaseModel):
    """Network access configuration.

    Controls code execution network permissions:
    - allow_network=False: block all network access
    - allow_network=True + allowed_hosts: allowlist only
    - allow_network=True + allowed_hosts=None: fully open
    """

    allow_network: bool = Field(default=False, description="Allow network access (default: disabled)")
    allowed_hosts: frozenset[str] | None = Field(
        default=None,
        description="Domain allowlist (None=use defaults, empty=unrestricted)",
    )

    def get_effective_allowed_hosts(self) -> frozenset[str] | None:
        """Get the effective domain allowlist.

        Returns:
            None: unrestricted; frozenset: only these domains allowed.
        """
        if not self.allow_network:
            return frozenset()

        if self.allowed_hosts is None:
            return DEFAULT_ALLOWED_HOSTS

        if len(self.allowed_hosts) == 0:
            return None

        return self.allowed_hosts


class ExecutionMode(StrEnum):
    """Code execution mode. Agent runs in a container, code executes locally."""

    LOCAL = "local"


class MCPIPCConfig(BaseModel):
    """MCP IPC configuration for subprocess-to-agent MCP tool callbacks via Unix Socket."""

    enabled: bool = Field(default=True, description="Enable MCP IPC")
    socket_path: str = Field(
        default="/tmp/myrm-agent-mcp/mcp.sock",
        description="Unix Socket file path",
    )


class LocalExecutionConfig(BaseModel):
    """Local execution configuration."""

    max_execution_time: int = Field(default=60, description="Max execution time (seconds)")
    shared_venv_path: str = Field(default="", description="Shared venv path (empty = system Python)")
    auto_create_venv: bool = Field(default=True, description="Auto-create shared venv")
    max_memory_mb: int = Field(default=2048, description="Max memory for single code execution in MB (0 to disable)")
    max_output_bytes: int = Field(
        default=5 * 1024 * 1024, description="Max output buffer bytes to prevent memory overflow"
    )


class ExecutionConfig(BaseModel):
    """Top-level execution configuration."""

    mode: ExecutionMode = Field(default=ExecutionMode.LOCAL, description="Execution mode")

    local: LocalExecutionConfig = Field(default_factory=LocalExecutionConfig)
    mcp_proxy: MCPIPCConfig = Field(default_factory=MCPIPCConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)


_execution_config_cache: ExecutionConfig | None = None


def get_execution_config() -> ExecutionConfig:
    """Get execution configuration (singleton, uses defaults if not explicitly set)."""
    global _execution_config_cache
    if _execution_config_cache is None:
        _execution_config_cache = ExecutionConfig()
    return _execution_config_cache


def set_execution_config(config: ExecutionConfig) -> None:
    """Set execution configuration (call before first use to override defaults)."""
    global _execution_config_cache
    _execution_config_cache = config
