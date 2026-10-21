"""Memory context subsystem — user memory injection into model calls.

Injects `<user_memory_context>` with scope boundary and untrusted data wrapping;
reuses `memory_brief_snapshot` when available to avoid preview/execution drift;
records injection/budget telemetry via API hooks for the server.

[INPUT]
- agent.memory (memory manager)
- langchain_core.messages (message models)

[OUTPUT]
- MemoryContextMiddleware: user memory context injection middleware
"""

from myrm_agent_harness.agent.middlewares.memory_context.memory_context_middleware import (
    MemoryContextMiddleware,
)

__all__ = ["MemoryContextMiddleware"]
