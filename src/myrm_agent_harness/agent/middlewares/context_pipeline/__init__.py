"""Context pipeline subsystem — request-time context assembly and budget.

[INPUT]
- langchain_core.messages (message models)
- agent.context_management (pipeline processors)

[OUTPUT]
- create_context_pipeline_middleware(): middleware factory integrating ContextPipeline
"""

from myrm_agent_harness.agent.middlewares.context_pipeline.context_pipeline_middleware import (
    create_context_pipeline_middleware,
)

__all__ = ["create_context_pipeline_middleware"]
