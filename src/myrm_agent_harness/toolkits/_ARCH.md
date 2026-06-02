# toolkits/

## Overview
Generic, framework-agnostic toolkit collection — analogous to lodash for Node.js.
Each toolkit is a **self-contained, absolutely independent** module usable via
`myrm_agent_harness.toolkits.xxx` by any consumer, without requiring the Agent runtime.

## Allowed Dependencies

- `core/` — framework-agnostic foundations (security, config, events, hooks, artifacts, features)
- `utils/` — generic utilities (no domain semantics)
- `infra/` — infrastructure primitives (delivery, locks, db)
- `observability/` — metrics, diagnostics, tracing (framework infrastructure, like logging)

## Forbidden Dependencies

- `agent/` — **NEVER**, including `TYPE_CHECKING` and lazy imports
- `backends/` — use `toolkits.storage` directly if needed
- `runtime/` — Agent runtime lifecycle is not a toolkit concern

## Gate Criteria

### When to place code in toolkits/

✅ Generic capability usable by **any** project — not tied to the Agent runtime
✅ Zero imports from `agent/` — not even under `TYPE_CHECKING` or lazy import
✅ Fully self-contained — can be tested in isolation without Agent setup

### When NOT to place code in toolkits/

❌ **Agent-specific tool wrappers** (e.g. `goal_agent_tools`) → `agent/meta_tools/`
❌ **Code requiring Agent runtime context** (e.g. session state, planner) → `agent/`
❌ **Wrappers around Agent subsystems** (e.g. planner tools) → `agent/sub_agents/`

### Decision Flow

```
Does your code need to import anything from agent/?
├─ YES → Does NOT belong in toolkits/. Place it in agent/meta_tools/ or agent/.
└─ NO  → Can it work without Agent runtime context?
         ├─ YES → ✅ Belongs in toolkits/
         └─ NO  → Does NOT belong in toolkits/
```

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Toolkits module export file. Provides various toolkits and services for Agent use: | ✅ |

| Submodule | Description |
|-----------|-------------|
| acp/ | ACP protocol integration — server and runtime components for Agent Communication Protocol. |
| automation/ | Rule-based agent task automation — CRUD for automation rules (event/schedule/manual triggers). |
| browser/ | Browser automation — multi-tab control, iframe traversal, session vault, stealth mode. |
| calendar/ | Calendar event management — CRUD operations via Protocol-based dependency injection. |
| code_execution/ | Code execution system — Agent-in-Sandbox mode with multiple executor backends. |
| commitment/ | Commitment tracking — implicit promise detection and follow-up from conversations. |
| computer_use/ | System-wide desktop automation — screen capture + coordinate-based input (macOS/Linux). |
| cron/ | Scheduled task framework — scheduling engine, CRUD manager, built-in strategies. |
| file_parsers/ | File format parsers — PDF, DOCX, Excel, text, and structured data extraction. |
| huggingface/ | Hugging Face integration — model and dataset tools for agents. |
| interaction/ | User interaction tools — AskQuestion dialog and clipboard operations. |
| kanban/ | Durable multi-task scheduling — heartbeat, zombie detection, run/event audit trail. |
| llms/ | LLM manager and adapters — 100+ provider support, citation extraction, image gen/edit. |
| local_browser_data/ | Local browser data search — Chrome/Edge bookmarks and history indexing. |
| local_file_search/ | Semantic search over local files — SHA256 incremental indexing, hybrid retrieval. |
| mcp/ | MCP protocol support — client management, tool fetching, connection pooling. |
| memory/ | Pluggable memory system — vector/relational/graph storage for AI agents. |
| notification/ | Cross-channel notification delivery — Protocol-based sender with rate limiting and whitelist security. |
| network/ | Network security — SSRF protection and URL validation for outbound requests. |
| openapi_bridge/ | OpenAPI Bridge — zero-code REST API integration via OpenAPI 3.x / Swagger 2.0 specs. |
| retriever/ | Retrieval and reranking — multi-source document retrieval with scoring pipeline. |
| storage/ | Storage abstraction layer — Protocol + local filesystem implementation. |
| tasks/ | Task management — task models, executor protocol, persistence layer. |
| vector/ | Vector Store — unified async vector storage and retrieval. |
| vision/ | Vision processing — image analysis fallback engine and video frame extraction. |
| web_fetch/ | Web content crawling — layered engine with HTTP/Browser/Stealth fallback chain. |
| web_search/ | Web search — multi-engine search tools with result aggregation. |
| wiki/ | Self-evolving knowledge base — LLM-powered wiki article generation and management. |
| workspace/ | Workspace path suggestion — bounded file enumeration and GUI-friendly fuzzy ranking. |
