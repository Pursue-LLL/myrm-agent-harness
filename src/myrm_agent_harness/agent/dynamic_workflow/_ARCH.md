# dynamic_workflow/ — Dynamic Workflow Engine

## Overview
The Dynamic Workflow Engine is the **DW PTC** branch of the PTC family (Programmatic Tool Calling). It breaks single-agent context limits by generating Python orchestration scripts that run in the Workflow RPC sandbox (`ptc/`) and spawn sub-agents concurrently through the delegate path.

**PTC 家族 SSOT**：`toolkits/code_execution/EXECUTION_SYSTEM.md` § PTC 家族。MCP PTC（bash + skills IPC）为同族另一分支，用户无感。

PTC tool classification: [../tool_management/TOOL_MANAGEMENT_SYSTEM.md](../tool_management/TOOL_MANAGEMENT_SYSTEM.md) §内部分类.

Detailed design: [DYNAMIC_WORKFLOW_SYSTEM.md](DYNAMIC_WORKFLOW_SYSTEM.md)

## Architecture

```
User Request (use_workflow=True)
       ↓
Server API (stream_loop.py → stream_lane_factory.py)
  - Budget gate: should_block_execution()
  - Token tracker: init_token_tracker() ... reset_token_tracker()
  - Agent factory: build_general_agent(wrapper, chat_id) → BaseAgent
       ↓
Dynamic Workflow Engine (__init__.py)
  - cancel_token checked at each phase boundary
       ↓
LLM generates Python Script (ORCHESTRATOR_PROMPT)
  - Pattern selection guide (barrier/pipeline/diamond)
  - Data transformation anti-delegation rules
  - Error isolation templates (try/except per spawn)
  - Partial failure handling guidance
  - Structured JSON output
       ↓
Trust layer (preflight + HITL)
  - Static count of `myrm_tools.spawn_subagent(` / `myrm_tools.llm_query(` / `llm_query_batched(` → cost estimate
  - SSE `phase=plan_confirm` + PhaseWaiter (`plan:{message_id}`)
  - User confirm/skip via `/agents/plan-confirm-response`
  - `WorkflowRunGuard`: max 50 spawns, concurrency semaphore 5
       ↓
PTC Sandbox Execution
       ↓
SpawnSubagentTool (tools.py)
  - spawn_prep.py → parent_agent._spawn_child()
  - Full tool registry inherited from parent
  - cancel_token checked before each spawn
  - readonly=True → READ_ONLY_SANDBOX; non-readonly → ISOLATED_COPY
       ↓
WorkflowEventStore (store.py) — L2 persistent cache (SpawnCacheParams fingerprint)
  - Matching params → cache hit
  - Param mismatch → re-spawn
       ↓
batch_merge — post-PTC finally workspace merge; `build_merge_snapshot_context` → Revert snapshots + summary diff
       ↓
Summarization LLM (SUMMARIZATION_PROMPT) + append `_workspace_diff` when workspace changed
       ↓
SSE events (message / message_end / status)
  - Frontend renders progress steps + final Markdown
```

## File Index

| File | Role | Description |
|------|------|-------------|
| `preflight.py` | Trust | Static spawn + llm_query counting, batch cost estimate, plan preview formatting, approval gate protocol. |
| `__init__.py` | Engine | Core entry point (`run_dynamic_workflow_stream`). Script generation (orchestrator 响应经 `utils.chat_utils::extract_answer_text` 提取，兼容内联 think 剥离与 reasoning 模型), preflight, optional `approval_gate`, PTC execution, summarization. |
| `store.py` | Persistence | `WorkflowEventStore` — fingerprinted sub-agent cache + orchestration script persistence. |
| `template_store.py` | Template library | `WorkflowTemplateStore` — user-named orchestration scripts for pinned reruns (`workflow_templates` table). |
| `template_validation.py` | Template library | Script validation, `extract_template_placeholders`, `validate_template_args`, AST `script_all_spawns_readonly`, placeholder substitution, trust-latch plan-confirm skip guardrails. |
| `paths.py` | Template library | `resolve_workflow_events_db_path` — SQLite path SSOT under `{harness_root}/.myrm/workflow_events.db`. |
| `spawn_cache.py` | Cache SSOT | `SpawnCacheParams` fingerprint for durable replay. |
| `tools.py` | PTC Tools | `SpawnSubagentTool` (WorkflowRunGuard, cache fingerprint, ISOLATED_COPY + merge) / `NotifyProgressTool` |
| `llm_query_tool.py` | PTC Tools | `LlmQueryTool` / `LlmQueryBatchedTool` — 轻量 LLM 直调原语（无子 agent）；批量保序、异常隔离、记账、共享预算熔断，且整批共享一次模型解析；响应提取复用 `utils.chat_utils::extract_answer_text`（兼容 str / Anthropic block list / 内联 think 剥离 / reasoning 模型 content 空时回退 reasoning_content） |
| `notify_stream.py` | Streaming | `iter_notify_events_while_task_runs` concurrently drains the notify queue while PTC execution runs; honors `cancel_token` cancellation. |
| `_ARCH.md` | Doc | This architecture document. |

## Key Design Decisions

1. **Code-as-Orchestrator**: Complex logic (loops, branches, parallelism) is pushed to Python code, keeping the LLM context clean.
2. **Dynamic Type Discovery**: At script-generation time, `_build_available_types_hint(catalog)` queries the `SubagentCatalog` protocol (which includes YAML presets, JIT configs, AND user-defined database agents) and appends a listing of available `agent_type` values to `ORCHESTRATOR_PROMPT`. This is the same discovery path used by `delegate_task_tool`, ensuring DW and normal delegation see identical agent types. Falls back to the global `SUBAGENT_CONFIGS` registry when no catalog is provided.
3. **Delegate Path Integration**: Sub-agents are spawned through `parent_agent._spawn_child()`, the same path used by `delegate_task_tool`. This inherits the full tool registry, catalog config, cancel_token, and budget. When no catalog config is found for the requested agent_type, the fallback `SubagentConfig` inherits the parent agent's `model_resolver`, enabling intelligent model routing (cost-saving auto-routing to lighter models for simple tasks). The `SpawnSubagentTool` returns a dict including `status` (SubAgentStatus value) so the generated script can distinguish failure modes (e.g., `timed_out` vs `failed` vs `cancelled_by_budget`).
4. **Durable Execution**: The SQLite Event Store replays when `SpawnCacheParams` match. Writable rows are JSON-safe; `merged` skips re-spawn/re-merge; `pending` forces re-spawn. Defer keeps child workspaces until `batch_merge`. Merge registers revert snapshots and appends workspace diff to the summary message.
5. **PTC Integration**: Leverages existing PTC infrastructure to expose `spawn_subagent` (optional adversarial verification via `run_with_verification`) to the generated script securely. Spawn prep shared with delegate via `agent/sub_agents/spawn_prep.py`. Non-readonly DW spawns use ISOLATED_COPY + post-execution `batch_merge`.
6. **Aggregation Layer**: Raw stdout is summarized by a dedicated LLM call into user-readable Markdown, preventing raw script output from reaching users. The `SUMMARIZATION_PROMPT` includes confidence classification instructions that direct the LLM to prefix each major finding with a reliability indicator (✅ Verified / ⚠️ Unverified / ❌ Refuted / 💥 Failed) based on execution evidence such as tool output, test results, and `[Verification: PASS/FAIL]` markers from the adversarial verification system.
7. **Cancel Propagation**: `cancel_token` is checked at every phase boundary and passed to every `spawn_child()` call, ensuring the "Stop" button works.
8. **Budget & Cost Tracking**: Server brackets the DW execution with `should_block_execution()` (budget gate) and `init_token_tracker()` / `reset_token_tracker()` (cost tracking), matching the normal agent and consensus stream patterns.
9. **SSE Compatibility**: Events use standard `AgentEventType` values (`message`, `message_end`, `status`) so the frontend handler chain processes them correctly. The `completion_status` field in `message_end` accurately reflects success or failure.
10. **Readonly Mode**: `SpawnSubagentTool` supports a `readonly` parameter for analysis-only tasks (security audits, code reviews, scanning). When `readonly=True`, dual protection is applied: (1) soft enforcement via `disallowed_tools` blocking write/bash/git tools, and (2) hard enforcement via `WorkspacePolicy.READ_ONLY_SANDBOX` which triggers `ReadonlyExecutorProxy` at the OS level. This matches the readonly capability already present in `delegate_task_tool`.
11. **Real-time Stage Notifications**: `NotifyProgressTool` bridges PTC scripts to the frontend SSE stream via an `asyncio.Queue`. The LLM-generated script calls `myrm_tools.notify()` at phase boundaries; the DW engine concurrently drains the queue **while** PTC execution runs, yielding `workflow_stage` events to the client without waiting for `inject_ptc` to finish. Frontend `statusStreamEvents` merges by `workflow_stage:${category}` and mirrors `notify_progress` → `progress_percent` (same UX contract as `ptc_notify`). The frontend's `ProgressItem` type already supports `notify_message`, `notify_progress`, `notify_step_index`, `notify_total_steps`, `notify_category`, and `notify_level` fields, requiring no new UI types. Events use SSE `step_key="workflow_stage"` for routing. `SpawnSubagentTool` emits start/done stage events on the same queue (`notify_category=subagent`).
