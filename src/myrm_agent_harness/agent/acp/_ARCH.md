# agent/acp/

## Overview
Standalone ACP server entry and default agent factory. Protocol server/runtime implementation lives in `toolkits/acp/`; this package wires a minimal `BaseAgent` for CLI `python -m myrm_agent_harness.agent.acp` usage.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports DefaultAgentFactory and SkillAgentFactory | ✅ |
| default_factory.py | Core | DefaultAgentFactory — creates BaseAgent per ACP session. LLM: injected model, else `LLMConfig`, else `MYRM_*` env via `LLMManager.get_llm_from_config`; with none configured `create_agent` raises (no stand-in model) | ✅ |
| skill_factory.py | Core | SkillAgentFactory — creates full-featured SkillAgent with dynamic MCP per ACP session | ✅ |
| __main__.py | CLI | Module entry for standalone ACP server (stdio / UDS socket) | ✅ |

## Division vs toolkits/acp/

| Package | Responsibility |
|---------|----------------|
| `agent/acp/` | Default agent factory + CLI entry for standalone ACP |
| `toolkits/acp/` | ACP protocol server, runtime backends, permission, event bus |

## Module Dependencies

- `agent.base_agent::BaseAgent` (POS: Lightweight agent with streaming and artifacts)
- `core.config.llm::LLMConfig` (POS: LLM configuration; `from_env()` reads `MYRM_MODEL_NAME` / `MYRM_API_KEY`)
- `toolkits.llms::LLMManager` (POS: Cached `LLMConfig` to chat model construction) [lazy]
