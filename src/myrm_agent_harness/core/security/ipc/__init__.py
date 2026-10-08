"""Safe Subprocess and File-Descriptor IPC Pipeline module.

[INPUT]
None.

[OUTPUT]
Exported public classes, functions, and exceptions.

[POS]
Harness core security subsystem for shell-free, injection-proof inter-process communication.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.ipc.pipeline import (
    SafeIpcPipeline,
)
from myrm_agent_harness.core.security.ipc.secure_file import (
    SecureIpcFile,
    read_query_file,
)
from myrm_agent_harness.core.security.ipc.types import (
    IpcExecutionResult,
    IpcPayloadTransport,
    SecureIpcFileOptions,
    ShellArgumentInjectionError,
)

__all__ = [
    "IpcExecutionResult",
    "IpcPayloadTransport",
    "SafeIpcPipeline",
    "SecureIpcFile",
    "SecureIpcFileOptions",
    "ShellArgumentInjectionError",
    "read_query_file",
]
