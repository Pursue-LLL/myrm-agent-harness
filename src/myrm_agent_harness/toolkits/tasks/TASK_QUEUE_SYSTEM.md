# Task Queue System

## Purpose

Framework-agnostic async job queue for **long-running media work inside a conversation**.
Current product `task_type`: `image_generate`, `video_generate`; additional media types use the same queue + executor pattern.

The harness owns **task models, store protocol, and SQLite persistence**. It does **not**
own the worker loop, REST/SSE surface, payload encryption, or UI cards — those belong to the
host application (Myrm server + frontend).

**Not an agent tool** — no `*_agent_tools.py`; zero LLM token footprint.

## Layer Placement

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend: ImageTaskCard + useTasksSubscription             │  UI
├─────────────────────────────────────────────────────────────┤
│  Server: app/api/tasks/ (REST + SSE /stream)                │  HTTP
├─────────────────────────────────────────────────────────────┤
│  Server: app/tasks/ (TaskWorker, executors, crypto, events) │  Business orchestration
├─────────────────────────────────────────────────────────────┤
│  Server: app/lifecycle/task_worker.py (store singleton)    │  Lifecycle wiring
├─────────────────────────────────────────────────────────────┤
│  Harness: toolkits/llms/image/async_image_engine.py         │  Media enqueue adapter
│  Harness: toolkits/llms/media_task_types.py                 │  Payload/result DTOs
├─────────────────────────────────────────────────────────────┤
│  Harness: toolkits/tasks/                                   │  Framework queue (this module)
│  (Task, TaskStatus, SQLiteTaskStore, AsyncTaskExecutor)     │
└─────────────────────────────────────────────────────────────┘
```

## When to Use

| Scenario | Use `toolkits/tasks/`? | Rationale |
|----------|------------------------|-----------|
| User asks for image in chat; need `task_id` + progress card | **Yes** | Blocks LLM turn if synchronous |
| Video/TTS batch with same chat-bound UX | **Yes** | Same queue + executor pattern |
| Daily briefing at 8:00 | **No** → `toolkits/cron/` | Time/trigger driven |
| Multi-agent project board with heartbeats | **No** → `toolkits/kanban/` | Orchestration, not single job |
| Deep crawl job groups | **No** → `toolkits/web_fetch/task_store.py` | Crawl-specific semantics |
| Agent idle memory consolidation | **No** → `agent/background_worker/` | Runs when agent is inactive |
| Sub-second web search / fetch | **No** | Direct tool call |

**Rule of thumb:** need a **`task_id` tied to the same chat message** with a **progress UI**?
→ `toolkits/tasks/`. Otherwise pick the sibling module above.

## Harness Layer Cheatsheet

| Layer | One line | Memory hook |
|-------|----------|-------------|
| `core/` | Foundation types (security, config, events) — no domain jobs | Brick |
| `toolkits/` | Self-contained capability packages — import without Agent | Plugin |
| `agent/` | LLM turn logic, session, streaming, HITL, meta_tools | Brain |
| `runtime/` | Single Agent **instance** survival (checkpoint, memory pressure, doctor) | Instance caretaker |
| `infra/` | Atomic primitives (locks, pubsub, delivery) | Plumbing |

### Code placement (single decision tree)

```
Does this code import agent/ or require the current chat session at definition time?
├─ YES → agent/meta_tools/ or host server business layer
└─ NO  → Is it a complete reusable capability package?
         ├─ YES → toolkits/ (tasks, cron, kanban, llms, …)
         └─ NO  → Pure type/security primitive?
                  ├─ YES → core/ or infra/
                  └─ NO  → Manages Agent instance health (checkpoint, quota)?
                           ├─ YES → runtime/
                           └─ NO  → Revisit design
```

`toolkits/tasks/` is a **toolkit capability**, not `core/`, `runtime/`, or `agent/`.

## Sibling Job Modules

| Module | Trigger | Persistence | User-visible artifact |
|--------|---------|-------------|------------------------|
| `toolkits/tasks/` | Agent tool during chat | `SQLiteTaskStore` (`tasks.db`) | `task_id` + ImageTaskCard |
| `toolkits/cron/` | Schedule / webhook / poll | CronStore | Cron job history |
| `toolkits/kanban/` | Planner / user board | KanbanStore | Kanban card + SSE |
| `web_fetch/CrawlTaskStore` | Deep crawl pipeline | Crawl-specific SQLite | Crawl group status |
| `agent/background_worker/` | Agent idle window | IdleTaskRegistry | None (maintenance) |

## Integration Recipes

### Standalone harness consumer (no Agent)

```python
from myrm_agent_harness.toolkits.tasks import SQLiteTaskStore, Task, TaskStatus

store = SQLiteTaskStore(db_path="tasks.db")
await store.create_task(task)
# Host implements worker loop + UI notification
```

### Async image enqueue (harness media adapter)

```python
from myrm_agent_harness.toolkits.llms.image.async_image_engine import AsyncImageGenerationTools

tools = AsyncImageGenerationTools(
    config=image_cfg,
    task_store=store,
    payload_postprocessor=seal_fn,  # optional; server injects for secrets
)
result_json = await tools.generate_image(prompt="...", chat_id="...")
# → {"task_id": "img-...", "status": "pending"}
```

### Myrm product full chain

1. `image_agent_tool` / `video_agent_tool` → `Async*GenerationTools.generate_*`
2. `seal_task_payload_secrets` (server) before `SQLiteTaskStore.create_task`
3. `TaskWorker` + media executors (`ImageTaskExecutor`, `VideoTaskExecutor`) consume queue
4. `TaskEventBus` → SSE `/api/v1/tasks/stream` → task cards (`ImageTaskCard` / `VideoTaskCard`)

## Crypto Boundary

- **Harness store**: crypto-agnostic JSON payload in SQLite
- **Server** `task_payload_crypto.py`: seals `api_key` and `gateway_config.auth_token`
  **before** persist; worker opens via `open_task_payload_secrets` only

## Extending task_type

1. Add payload/result DTO in `toolkits/llms/media_task_types.py`
2. Implement `AsyncTaskExecutor` in host server (`app/tasks/executors/`)
3. Register executor in `TaskWorker` — **queue layer unchanged**

## Key Files

| Location | Role |
|----------|------|
| `toolkits/tasks/protocols.py` | `Task`, `TaskStatus`, retry policy |
| `toolkits/tasks/store.py` | `SQLiteTaskStore` |
| `toolkits/tasks/executor.py` | `AsyncTaskExecutor` protocol |
| `toolkits/llms/image/async_image_engine.py` | Image enqueue |
| `myrm-agent-server/app/tasks/worker.py` | Consumer loop |
| `myrm-agent-server/app/lifecycle/task_worker.py` | Store singleton + startup |

## References

- Module index: [_ARCH.md](_ARCH.md)
- Toolkits gate: [../_ARCH.md](../_ARCH.md)
- Kanban layering pattern: [../kanban/_ARCH.md](../kanban/_ARCH.md)
