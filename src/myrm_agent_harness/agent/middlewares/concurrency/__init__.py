"""Concurrency subsystem — subagent limits and parallel tool execution routing.

[INPUT]
- langchain.agents.middleware (AgentMiddleware base)
- agent.security.tool_registry (SafetyMetadata for read-only / host-serial lanes)

[OUTPUT]
- create_concurrency_limiter(): subagent semaphore factory
- create_safety_dispatcher(): tool safety dispatch factory
- build_tool_execution_stages() / should_parallelize_tool_batch(): batch stage planners
"""

from myrm_agent_harness.agent.middlewares.concurrency.concurrency_limiter import (
    create_concurrency_limiter,
    get_subagent_semaphore,
)
from myrm_agent_harness.agent.middlewares.concurrency.concurrency_router import (
    build_tool_execution_stages,
    should_parallelize_tool_batch,
)
from myrm_agent_harness.agent.middlewares.concurrency.safety_dispatcher import (
    create_safety_dispatcher,
)

__all__ = [
    "build_tool_execution_stages",
    "create_concurrency_limiter",
    "create_safety_dispatcher",
    "get_subagent_semaphore",
    "should_parallelize_tool_batch",
]
