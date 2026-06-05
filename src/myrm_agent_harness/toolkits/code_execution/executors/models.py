"""Data models for code execution.

Defines execution context, results, MCP communication configuration,
and execution metrics.

[INPUT]
- (none)

[OUTPUT]
- AsyncProcessProtocol: Subprocess handle exposed by CodeExecutor (stdio MCP and ...
- MCPConfigItem: MCP tool configuration item.
- MCPCommunicationConfig: MCP IPC communication config provided by CodeExecutor.
- ExecutionContext: Execution context (framework layer).
- ExecutionResult: Execution result.

[POS]
Data models for code execution.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field


@runtime_checkable
class AsyncProcessProtocol(Protocol):
    """Subprocess handle exposed by CodeExecutor (stdio MCP and similar)."""

    @property
    def stdin(self) -> object: ...

    @property
    def stdout(self) -> object: ...

    @property
    def stderr(self) -> object: ...

    async def wait(self) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


@dataclass
class MCPConfigItem:
    """MCP tool configuration item."""

    name: str
    type: str = "stdio"
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> MCPConfigItem:
        """Create MCPConfigItem from a dictionary."""
        args_raw = data.get("args")
        args_list: list[str] | None = None
        if args_raw and isinstance(args_raw, list):
            args_list = [str(arg) for arg in args_raw]

        env_raw = data.get("env")
        env_dict: dict[str, str] | None = None
        if env_raw and isinstance(env_raw, dict):
            env_dict = {str(key): str(value) for key, value in env_raw.items()}

        return cls(
            name=str(data.get("name", "")),
            type=str(data.get("type", "stdio")),
            command=str(data.get("command")) if data.get("command") else None,
            args=args_list,
            env=env_dict,
            url=str(data.get("url")) if data.get("url") else None,
            description=str(data.get("description", "")),
        )

    @classmethod
    def from_dict_list(cls, data_list: list[dict[str, object]]) -> list[MCPConfigItem]:
        """Create a list of MCPConfigItem from dictionaries."""
        return [cls.from_dict(data) for data in data_list]


@dataclass
class MCPCommunicationConfig:
    """MCP IPC communication config provided by CodeExecutor."""

    socket_path: str | None = None
    skip_local_proxy: bool = False
    servers: list[MCPConfigItem] = field(default_factory=list)


@dataclass
class ExecutionContext:
    """Execution context (framework layer)."""

    code: str
    original_code: str | None = None
    args: list[str] | None = None
    session_id: str | None = None
    work_dir: str = "/workspace"
    workspace_root: str | None = None
    active_skills: list[str] | None = None
    allow_network: bool = False
    allowed_hosts: frozenset[str] | None = None
    timeout: int = 60
    max_memory_mb: int = 2048
    max_cpu_cores: float = 2.0
    env: dict[str, str] | None = None
    mcp_config: list[MCPConfigItem] | None = None
    readonly_workspace: bool = False


@dataclass
class ExecutionResult:
    """Execution result.

    Output safety: stdout/stderr are auto-truncated and scrubbed across all
    execution backends.
    """

    success: bool | None = None
    result: object | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    error_category: str | None = None
    error_hint: str | None = None
    plots: list[str] = field(default_factory=list)
    execution_time: float = 0.0
    container_id: str | None = None
    generated_files: list[str] = field(default_factory=list)
    exit_code: int | None = None
    """Originating OS process exit code (if applicable)."""

    def __post_init__(self) -> None:
        from myrm_agent_harness.toolkits.code_execution.executors.common.executor_utils import (
            truncate_output,
        )

        self.stdout = scrub_sensitive_info(truncate_output(self.stdout))
        self.stderr = scrub_sensitive_info(truncate_output(self.stderr))

        if self.success is None:
            if self.exit_code is not None:
                self.success = self.exit_code == 0
            else:
                self.success = self.error is None

        if self.success is False and self.error_category is None:
            self.error_category = classify_execution_error(self)

        if self.success is False and self.error_hint is None:
            self.error_hint = generate_error_hint(self)


_ERROR_PATTERNS: list[tuple[str, list[str]]] = [
    ("timeout", ["timeout", "timed out", "TimeoutError"]),
    (
        "oom",
        [
            "out of memory",
            "MemoryError",
            "OOMKilled",
            "Cannot allocate memory",
            "exit code 137",
        ],
    ),
    ("sandbox_ro", ["Read-only file system", "EROFS"]),
    (
        "network_blocked",
        [
            "urllib.error.URLError",
            "ConnectionRefusedError",
            "NewConnectionError",
            "Name or service not known",
            "Temporary failure in name resolution",
            "Network is unreachable",
        ],
    ),
    (
        "permission",
        ["Permission denied", "PermissionError", "EACCES", "Operation not permitted"],
    ),
    ("syntax", ["SyntaxError", "IndentationError", "TabError", "syntax error"]),
    ("import", ["ModuleNotFoundError", "ImportError", "No module named"]),
    (
        "not_found",
        ["FileNotFoundError", "No such file or directory", "command not found"],
    ),
]


def classify_execution_error(result: ExecutionResult) -> str | None:
    """Classify an execution error into a structured category."""
    if result.success:
        return None

    if result.exit_code is not None:
        if result.exit_code == 124:
            return "timeout"
        if result.exit_code in (137, -9):
            return "oom"
        if result.exit_code == 127:
            return "not_found"

    combined = " ".join(filter(None, [result.error, result.stderr, result.stdout[:500]]))
    for category, patterns in _ERROR_PATTERNS:
        if any(pattern in combined for pattern in patterns):
            return category

    return "unknown"


_MODULE_NAME_RE = re.compile(r"No module named ['\"]?([a-zA-Z0-9_]+)")
_COMMAND_NOT_FOUND_RE = re.compile(r"(\S+): (?:command not found|not found)")
_PERMISSION_PATH_RE = re.compile(r"Permission denied[:\s]+['\"]?([^\s'\"]+)")

_IMPORT_TO_PYPI: dict[str, str] = {
    "PIL": "Pillow",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "skimage": "scikit-image",
    "yaml": "PyYAML",
    "bs4": "beautifulsoup4",
    "attr": "attrs",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "gi": "PyGObject",
    "wx": "wxPython",
    "serial": "pyserial",
    "usb": "pyusb",
    "Crypto": "pycryptodome",
    "jwt": "PyJWT",
    "magic": "python-magic",
}


def _lookup_install_hint(bin_name: str) -> str | None:
    """Look up a platform-specific install command from the CLI tool catalog."""
    from myrm_agent_harness.toolkits.code_execution.tool_discovery.detector import (
        get_install_hint,
    )

    return get_install_hint(bin_name)


def _get_preferred_pip_installer() -> str:
    """Return ``uv pip`` if uv is detected, otherwise ``pip``."""
    from myrm_agent_harness.toolkits.code_execution.tool_discovery.detector import (
        detect_all,
    )

    for tool in detect_all():
        if tool.id == "uv":
            return "uv pip"
    return "pip"


def generate_error_hint(result: ExecutionResult) -> str | None:
    """Generate an actionable fix hint based on error_category and stderr."""
    category = result.error_category
    if not category or category in {"syntax", "unknown"}:
        return None

    combined = " ".join(filter(None, [result.error, result.stderr]))

    if category == "import":
        match = _MODULE_NAME_RE.search(combined)
        if match:
            module = match.group(1)
            pypi_name = _IMPORT_TO_PYPI.get(module, module)
            installer = _get_preferred_pip_installer()
            return f"Try: {installer} install {pypi_name}"
        return "A Python module is missing. Install it with pip install <module_name>."

    if category == "not_found":
        match = _COMMAND_NOT_FOUND_RE.search(combined)
        if match:
            command = match.group(1)
            install_cmd = _lookup_install_hint(command)
            if install_cmd:
                return f"Command '{command}' not found. Try: {install_cmd}"
            return f"Command '{command}' not found. Install it or check the PATH."
        return "A command was not found. Verify spelling and PATH."

    if category == "permission":
        match = _PERMISSION_PATH_RE.search(combined)
        if match:
            path = match.group(1)
            return f"Try: chmod +x {path}"
        return "Permission denied. Check file permissions with ls -la and use chmod."

    if category == "sandbox_ro":
        return "[SYSTEM_ENFORCED] Current mount is read-only. You MUST write output to the /workspace directory."

    if category == "network_blocked":
        return (
            "[SYSTEM_ENFORCED] Network access is strictly blocked in this sandbox. "
            "Do NOT retry with different HTTP libraries (urllib, requests, curl, etc). "
            "Change your approach (e.g. generate mock data or ask the user)."
        )

    if category == "timeout":
        return "Execution timed out. Try reducing input size, splitting into smaller tasks, or increasing the timeout."

    if category == "oom":
        return "Out of memory. Try processing data in smaller chunks or reducing memory usage."

    return None


_PATH_SCRUB_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"/(Users|home)/[^/\s\"'<>)]+"), "<HOME>"),
    (re.compile(r"\\/(Users|home)\\/[^/\\\s\"'<>)]+"), "<HOME>"),
    (re.compile(r"[a-zA-Z]:\\Users\\[^\s\"'<>)]+"), "<HOME>"),
    (re.compile(r"(?i)/(tmp|private|var|etc|opt|usr)/[^/\s\"'<>)]+"), "<ABS_PATH>"),
]


def scrub_sensitive_info(text: str) -> str:
    """Scrub sensitive information from text: absolute paths + credential tokens.

    Path scrubbing (unique to this function): replaces host-identifying paths
    like ``/Users/xxx`` with ``<HOME>`` to prevent host privacy leakage.

    Credential scrubbing: delegates to ``redact_sensitive_text`` which covers
    30+ API key prefixes, ENV/JSON/Header/DB/URL/CLI patterns with ReDoS-safe
    bounded replace.
    """
    if not text:
        return text

    for pattern, replacement in _PATH_SCRUB_PATTERNS:
        text = pattern.sub(replacement, text)

    from myrm_agent_harness.core.security.redact import redact_sensitive_text

    return redact_sensitive_text(text)


@dataclass
class ExecutionMetrics:
    """Cumulative execution statistics for monitoring and telemetry."""

    total_executions: int = 0
    total_python: int = 0
    total_bash: int = 0
    total_success: int = 0
    total_failures: int = 0
    total_time: float = 0.0
    max_time: float = 0.0
    error_counts: dict[str, int] = field(default_factory=dict)
    _start_time: float = field(default_factory=time.monotonic)

    @property
    def execution_count(self) -> int:
        return self.total_executions

    @property
    def error_count(self) -> int:
        return self.total_failures

    @property
    def total_time_ms(self) -> float:
        return self.total_time * 1000

    def record(self, result: ExecutionResult, execution_type: Literal["python", "bash"]) -> None:
        """Record a single execution result."""
        self.total_executions += 1

        if execution_type == "python":
            self.total_python += 1
        else:
            self.total_bash += 1

        if result.success:
            self.total_success += 1
        else:
            self.total_failures += 1
            category = result.error_category or "unknown"
            self.error_counts[category] = self.error_counts.get(category, 0) + 1

        self.total_time += result.execution_time
        if result.execution_time > self.max_time:
            self.max_time = result.execution_time

    @property
    def avg_time(self) -> float:
        """Average execution time in seconds."""
        return self.total_time / self.total_executions if self.total_executions > 0 else 0.0

    @property
    def success_rate(self) -> float:
        """Success rate as a fraction (0.0 to 1.0)."""
        return self.total_success / self.total_executions if self.total_executions > 0 else 0.0

    @property
    def uptime(self) -> float:
        """Seconds since metrics were created."""
        return time.monotonic() - self._start_time

    def to_dict(self) -> dict[str, object]:
        """Export metrics as a dictionary for structured logging and reporting."""
        return {
            "total_executions": self.total_executions,
            "python_executions": self.total_python,
            "bash_executions": self.total_bash,
            "success_count": self.total_success,
            "failure_count": self.total_failures,
            "success_rate": round(self.success_rate, 4),
            "total_time_seconds": round(self.total_time, 3),
            "total_time_ms": round(self.total_time_ms, 3),
            "avg_time_seconds": round(self.avg_time, 3),
            "max_time_seconds": round(self.max_time, 3),
            "uptime_seconds": round(self.uptime, 1),
            "execution_count": self.execution_count,
            "error_count": self.error_count,
            "error_counts": dict(self.error_counts),
        }


class ExecutorConfig(BaseModel):
    """Configuration for code executors."""

    timeout: int = Field(default=60, ge=1, le=300)
    workdir: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    memory_limit_mb: int = 512
    network_enabled: bool = False


class SandboxProcessInfo(BaseModel):
    """Process info from inside a sandbox."""

    pid: int
    ppid: int
    user: str
    command: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
