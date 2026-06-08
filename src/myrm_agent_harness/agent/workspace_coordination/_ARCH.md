# workspace_coordination/

## Overview
Parallel subagent workspace safety helpers — write isolation policy and serial merge of deferred ISOLATED_COPY workspaces.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports policy and batch merge helpers | — |
| policy.py | Core | `apply_parallel_write_isolation`, `count_parallel_writers` — WorkspacePolicy enforcement | — |
| batch_merge.py | Core | Serial merge of isolated child workspaces after parallel batch delegation | — |

## Module Dependencies

- `agent.sub_agents.types::SubagentConfig`, `WorkspacePolicy`
