"""Persistent Session Module

Provides persistent shell sessions that maintain state across commands.

Features:
- Environment variables persist across commands
- Working directory persists across commands
- Shell functions and aliases persist
- Session isolation (per chat_id)
- Health check and auto-recovery
- Performance optimization (20-100x improvement)

Notes:
- Python variables do NOT persist (each execution is isolated)
- Only Bash environment persists
- Use filesystem to pass data between Python executions
"""

from myrm_agent_harness.toolkits.code_execution.session.local_session import (
    LocalPersistentSession,
    create_persistent_session,
)
from myrm_agent_harness.toolkits.code_execution.session.persistent_session import (
    PersistentSession,
    SessionConfig,
    SessionExecutionResult,
)
from myrm_agent_harness.toolkits.code_execution.session.shell_flavor import (
    ShellFlavor,
)
from myrm_agent_harness.toolkits.code_execution.session.stream_output_processor import (
    StreamOutputProcessor,
)

__all__ = [
    "LocalPersistentSession",
    "PersistentSession",
    "SessionConfig",
    "SessionExecutionResult",
    "ShellFlavor",
    "StreamOutputProcessor",
    "create_persistent_session",
]
