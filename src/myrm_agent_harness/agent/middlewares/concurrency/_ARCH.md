# concurrency/

## Overview

Concurrency and parallel-execution controls — subagent semaphore limits, safe
tool dispatch, and smart tool batch routing by path scope and safety metadata.

Detailed design: [MIDDLEWARE_SYSTEM.md](../MIDDLEWARE_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public exports for concurrency factories and stage planners. | — |
| `concurrency_limiter.py` | Core | Subagent Semaphore by agent_type; `get_subagent_semaphore` accessor. | ✅ |
| `concurrency_router.py` | Core | Smart tool routing: host-serial MCP lane awareness, canonical path identity, default CWD scope reservation for omitted paths, precise `file_read_tool.paths[]` & alias/string conflict modeling, `build_tool_execution_stages()` + `should_parallelize_tool_batch()`. | ✅ |
| `safety_dispatcher.py` | Core | safe→concurrent / unsafe→serial tool routing middleware factory. | ✅ |

## Key Dependencies

- `agent.security.tool_registry` — SafetyMetadata, resolve_safety_metadata
- `langchain.agents.middleware` — AgentMiddleware base
