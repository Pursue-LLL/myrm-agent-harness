# toolkits/

## Overview
Generic, framework-agnostic toolkit collection — analogous to lodash for Node.js.
Each toolkit is a **self-contained, absolutely independent** module usable via
`myrm_agent_harness.toolkits.xxx` by any consumer, without requiring the Agent runtime.

## Architecture gate

**Framework vs business extension — do not confuse layers.** This is the primary cause of harness bloat.

| Layer | Location | What belongs | Examples |
|-------|----------|--------------|----------|
| **Framework primitives** | `toolkits/` + `agent/meta_tools/` | Generic, reusable capabilities any agent framework could ship; no vendor OAuth product flows | `web_fetch`, `web_search`, `browser`, `mcp`, `kanban`, `cron`, `bash_code_execute_tool` |
| **Agent runtime binding** | `agent/meta_tools/`, `agent/sub_agents/` | Wrappers that need session/planner/HITL context | `planner_tool`, `render_ui_tool`, file ops meta-tools |
| **Business workflows** | `myrm-agent-server/assets/prebuilt_skills/` | Prompt + contract + `allowed-tools`; orchestrates framework tools | `daily-briefing`, `blog-monitoring`, `github-workflow` |
| **Third-party integrations (product)** | `myrm-agent-server/app/api/integrations/`, MCP servers, channel providers | OAuth CRUD, channel SDKs, user-configured MCP | Feishu channel, `integrations/oauth.py`, user MCP |
| **Server REST domain** | `myrm-agent-server/app/api/` + `services/` | Product HTTP, not harness tools | kanban API, skills API |

### Hard rules (contributors)

1. **Never** add a third-party SaaS wrapper as a harness `toolkits/*` module (calendar, huggingface, rss-class integrations belong in skill/MCP).
2. **Never** ship a prebuilt skill that promises OAuth/API access without a working product integration path (GUI OAuth or documented MCP).
3. **Single-vendor narrow tools** → skill script + `bash_code_execute_tool` / `web_fetch_tool`, or user MCP — not a new harness toolkit.
4. **`allowed-tools` in SKILL.md** must use **registered tool names** (e.g. `bash_code_execute_tool`, not legacy alias `bash_tool`).
5. **Adding a harness tool** requires: generic reuse across projects, zero `agent/` imports, entry in `tool_layers.py` + `validate_tool_registry.py` PASS.

### Decision flow (framework vs business)

```
Is this a specific vendor/product integration (Google Calendar, HF Hub, RSS feed for one blog)?
├─ YES → Skill and/or MCP and/or server integrations/ — NOT toolkits/
└─ NO  → Is it generic infrastructure (fetch, search, sandbox, MCP client, kanban engine)?
         ├─ YES → toolkits/ (if agent-agnostic) or agent/meta_tools/ (if needs runtime)
         └─ NO  → Reconsider — likely belongs in server services/ or a skill only
```

`tests/architecture/test_toolkits_agent_boundary.py` fails if any
`toolkits/**/*.py` imports `myrm_agent_harness.agent.*`.

## Category Index

| Category | Toolkits | Role |
|----------|----------|------|
| **Core** | `code_execution/`, `storage/`, `llms/`, `memory/`, `mcp/`, `network/`, `security/`, `vector/`, `retriever/` | Runtime primitives: sandbox, LLM, persistence, MCP, SSRF guard |
| **Workspace** | `browser/`, `computer_use/`, `code_index/`, `workspace/`, `context/`, `file_parsers/`, `wiki/`, `element_ref/` | Files, browser, desktop, code search, context bundles |
| **Integration** | `a2a/`, `acp/`, `openapi_bridge/`, `web_fetch/`, `web_search/`, `deploy/`, `local_browser_data/`, `notification/` | External APIs, agent protocols, channels, deployment bridges |
| **Collaboration & Media** | `kanban/`, `tasks/`, `commitment/`, `automation/`, `cron/`, `interaction/`, `tts/`, `vision/` | Scheduling, tasks, user interaction primitives, media |
| **Observability** | `vnc/` | Real-time desktop streaming and human takeover coordination |

Agent-specific tool wrappers (e.g. `render_ui_tool`) live in `agent/meta_tools/`, not here.

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
| SECURITY_WRAPPER_GUIDE.md | L2 | Tool output security wrapping guide (`wrap_with_external_sources_tag` / `wrap_with_tool_output_tag`) | — |
| __init__.py | Package | Toolkits module export file. Provides various toolkits and services for Agent use: | ✅ |

| Submodule | Description |
|-----------|-------------|
| a2a/ | A2A (Agent-to-Agent) protocol support — AgentCard data models, client Resolver with SSRF protection, Provider Protocol contract. |
| acp/ | ACP protocol integration — server and runtime components for Agent Communication Protocol. |
| automation/ | Rule-based agent task automation — CRUD for automation rules (event/schedule/manual triggers). |
| browser/ | Browser automation — multi-tab control, iframe traversal, session vault, stealth mode. |
| code_execution/ | Code execution system — Agent-in-Sandbox mode with multiple executor backends. |
| code_index/ | Workspace code indexer — on-demand FTS5+Vector hybrid search over source code files. |
| commitment/ | Commitment tracking — implicit promise detection and follow-up from conversations. |
| computer_use/ | System-wide desktop automation — screen capture + coordinate-based input (macOS/Linux). |
| cron/ | Scheduled task framework — scheduling engine, CRUD manager, built-in strategies. |
| deploy/ | Artifact deployment — Protocol-based deploy tool with HITL approval via LangGraph interrupt. |
| context/ | Unified context bundle — volume layout, facade, index/lifecycle hook registration. |
| element_ref/ | Shared @dref element reference types and session-scoped registry for desktop control. |
| file_parsers/ | File format parsers — PDF, DOCX, Excel, text, and structured data extraction. |
| interaction/ | User interaction primitives — AskQuestion dialog and clipboard operations (UI rendering: `agent/meta_tools/interaction/`) |
| kanban/ | Durable multi-task scheduling — heartbeat, zombie detection, run/event audit trail. |
| llms/ | LLM manager and adapters — 100+ provider support, citation extraction, image gen/edit. |
| local_browser_data/ | Local browser data search — Chrome/Edge bookmarks and history indexing. |
| mcp/ | MCP protocol support — client management, tool fetching, connection pooling. |
| memory/ | Pluggable memory system — vector/relational/graph storage for AI agents. |
| notification/ | Cross-channel notification delivery — Protocol-based sender with rate limiting and whitelist security. |
| network/ | Network security — SSRF protection and URL validation for outbound requests. |
| openapi_bridge/ | OpenAPI Bridge — zero-code REST API integration via OpenAPI 3.x / Swagger 2.0 specs. |
| retriever/ | Retrieval and reranking — multi-source document retrieval with scoring pipeline. |
| security/ | Credential vault — in-memory password/TOTP resolution for tool execution. |
| storage/ | Storage abstraction layer — Protocol + local filesystem implementation. |
| tasks/ | Task management — task models, executor protocol, persistence layer. |
| tts/ | Text-to-speech — OpenAI/ElevenLabs engine with gateway fallback. |
| vector/ | Vector Store — unified async vector storage and retrieval. |
| vision/ | Vision processing — image analysis fallback engine and video frame extraction. |
| vnc/ | VNC visual desktop streaming — x11vnc + websockify + human takeover coordination. |
| web_fetch/ | Web content crawling — layered engine with HTTP/Browser/Stealth fallback; `[web]` extra for scrapling + YouTube transcripts. |
| web_search/ | Web search — multi-engine search tools with result aggregation. |
| wiki/ | Self-evolving knowledge base — LLM-powered wiki article generation and management. |
| workspace/ | Workspace path suggestion — bounded file enumeration and GUI-friendly fuzzy ranking. |
