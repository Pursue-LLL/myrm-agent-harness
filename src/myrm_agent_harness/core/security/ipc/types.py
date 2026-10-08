"""Type definitions for Safe File-Descriptor and Query-File IPC Pipeline.

[INPUT]
None.

[OUTPUT]
- IpcPayloadTransport: Transport mechanism enum (query_file, stdin_stream)
- SecureIpcFileOptions: Configuration options for secure temporary files
- IpcExecutionResult: Execution outcome of an IPC subprocess invocation
- ShellArgumentInjectionError: Exception raised when dangerous CLI string concatenation is detected

[POS]
Harness core security subsystem for shell-free, injection-proof inter-process communication.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class IpcPayloadTransport(StrEnum):
    """Transport mechanism for delivering payload to subprocess without CLI argument injection."""

    QUERY_FILE = "query_file"
    STDIN_STREAM = "stdin_stream"


@dataclass(frozen=True, slots=True)
class SecureIpcFileOptions:
    """Security settings for temporary query-file IPC pipelines."""

    base_dir: str | None = None
    prefix: str = "myrm_ipc_"
    mode: int = 0o600
    shred_before_unlink: bool = True


@dataclass(frozen=True, slots=True)
class IpcExecutionResult:
    """Subprocess execution output and telemetry."""

    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    query_file_path: str | None = None
    executed_at: float = field(default_factory=time.time)


class ShellArgumentInjectionError(Exception):
    """Raised when an execution attempts to pass raw prompt/message text as CLI arguments."""

    def __init__(self, message: str, flag: str | None = None) -> None:
        super().__init__(message)
        self.flag = flag
