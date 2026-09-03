# agent/acp/

## Overview
Standalone ACP server entry and default agent factory. Protocol server/runtime implementation lives in `toolkits/acp/`; this package wires a minimal `BaseAgent` for CLI `python -m myrm_agent_harness.agent.acp` usage.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports DefaultAgentFactory and SkillAgentFactory | ✅ |
| default_factory.py | Core | DefaultAgentFactory — creates BaseAgent per ACP session | ✅ |
| skill_factory.py | Core | SkillAgentFactory — creates full-featured SkillAgent with dynamic MCP per ACP session | ✅ |
| __main__.py | CLI | Module entry for standalone ACP server (stdio / UDS socket) | ✅ |

## Division vs toolkits/acp/

| Package | Responsibility |
|---------|----------------|
| `agent/acp/` | Default agent factory + CLI entry for standalone ACP |
| `toolkits/acp/` | ACP protocol server, runtime backends, permission, event bus |

## Module Dependencies

- `agent.base_agent::BaseAgent` (POS: Lightweight agent with streaming and artifacts)
