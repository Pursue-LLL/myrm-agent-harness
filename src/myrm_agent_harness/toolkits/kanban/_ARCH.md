# Kanban Toolkit Architecture

## Purpose

Durable multi-task scheduling with heartbeat monitoring, zombie detection,
auto-block on consecutive failures, transient error smart backoff, and
per-task retries.

Protocol-first architecture with strict framework-business separation.

## Layer Placement

```
┌─────────────────────────────────────────────┐
│  Frontend (KanbanSection + KanbanBoardView) │  UI layer
├─────────────────────────────────────────────┤
│  Server: api/kanban/ (REST endpoints)       │  HTTP layer
├─────────────────────────────────────────────┤
│  Server: services/kanban/ (KanbanService)   │  Business orchestration
├─────────────────────────────────────────────┤
│  Server: core/kanban/adapters/              │  Persistence adapters
│  (SqlAlchemyKanbanStore, ORM mapping)       │  (implements Protocol)
├─────────────────────────────────────────────┤
│  Harness: toolkits/kanban/                  │  Framework layer
│  (types, protocols, dispatcher, tools)      │  (pure domain + engine)
└─────────────────────────────────────────────┘
```

## Key Design Decisions

1. **Protocol-first**: `KanbanStore`, `TaskRunner`, `CompletionVerifier`,
   `TaskSpecifier`, and `TaskDecomposer` are `Protocol` classes. The harness
   defines behavior; the server injects concrete implementations.

2. **Event-driven dispatch**: `KanbanDispatcher` uses `asyncio.Event` for
   wake-on-change instead of fixed-interval polling. Tasks are processed
   immediately when added, not on the next poll cycle.

3. **Heartbeat + Zombie detection + Progress notes**: Running tasks send periodic
   heartbeats with exception-tolerant retry (store transient errors log a warning
   but do not crash the heartbeat loop). The zombie loop reclaims tasks whose
   heartbeat exceeds `zombie_timeout_seconds`.
   Agents can also send manual heartbeats with a `note` parameter to report granular
   progress (e.g. "Step 2/5: Parsing data…"). Notes are stored on `KanbanTask.progress_note`
   for instant UI display and appended to the event log as `HEARTBEAT` events for audit.
   Notes are automatically cleared when a task completes, fails, or is reclaimed as a zombie. When a note is provided,
   a `heartbeat_progress` event is emitted via the dispatcher's event callback chain,
   enabling real-time SSE push to the frontend.

4. **Auto-block + Block semantics (BlockKind)**: Tasks that fail
   `auto_block_after_consecutive_failures` times are moved to BLOCKED status with
   `block_kind=HUMAN` to prevent infinite retry loops. The `BlockKind` enum
   (HUMAN / SCHEDULED / EXTERNAL) semantically distinguishes *why* a task is blocked:
   - `HUMAN`: Needs human intervention (e.g. PR review, manual approval, auto-blocked failures).
   - `SCHEDULED`: Waiting for a specific time — dispatcher auto-unblocks when `scheduled_until` passes.
   - `EXTERNAL`: Waiting for an external event (e.g. CI/CD pipeline, webhook callback).
   The `_zombie_loop` calls `_wakeup_scheduled_tasks()` each cycle, which queries
   `list_due_scheduled_tasks(board_id)` for BLOCKED+SCHEDULED tasks past their deadline,
   moves them to READY, and emits `UNBLOCKED` events with `source=auto_schedule`.
   `kanban_block` tool accepts an `until` param (ISO-8601 or duration shorthand like `30m`, `2h`)
   to create scheduled blocks. Frontend renders distinct icons per block kind and a live
   countdown for scheduled blocks.

5. **Chat session linkage**: When an orchestrator creates tasks from a chat session,
   `metadata.source_chat_id` is injected server-side (not exposed in LLM tool schema).
   Orchestrator `kanban_list_tasks` auto-scopes to the session via closure (no schema change).
   The REST list endpoint supports `source_chat_id` filtering; the board UI reads
   `?source_chat=` from the URL. Task drawer links back to the originating chat.

6. **Completion Verification (Hallucination Gate)**: When a `CompletionVerifier` is
   injected into the dispatcher, it intercepts `_handle_success` before marking a task
   COMPLETED. Tasks with `metadata["completion_criteria"]` trigger an LLM judge call.
   Verification failure emits `VERIFICATION_FAILED` event and routes to `_handle_failure`
   (leveraging existing retry/auto-block). Tasks without criteria pass through transparently.
   60-second timeout prevents verifier hangs from blocking the dispatcher.

7. **Complete event chain**: Every lifecycle transition produces a `TaskEvent`.
   Task creation emits `CREATED`, status moves emit their corresponding kind,
   and `list_events` supports `since_id` for incremental catch-up.

8. **Task dependency DAG**: Tasks can declare dependencies via `TaskEdge`
   (parent→child). New tasks with dependencies start in `BACKLOG`. When all
   parents reach a terminal status, the dispatcher's `_promote_dependents`
   automatically moves children to `READY` and emits a `PROMOTED` event.
   Cycle detection uses DFS at edge-insertion time to guarantee a valid DAG.

9. **TRIAGE inbox + LLM Specifier**: `TRIAGE` is the inbox state for rough
   user ideas pending LLM-driven rewrite into a structured spec (Goal /
   Approach / Acceptance criteria / Out of scope). The dispatcher treats
   TRIAGE as opaque — never claimed for execution. The `TaskSpecifier`
   protocol owns the LLM call and returns a `SpecifyOutcome` (never raises
   for expected failure modes — failures surface via `ok=False` so batch
   sweeps can continue). Only `BACKLOG / READY / ARCHIVED` are valid
   transitions out of TRIAGE (`_TRIAGE_ALLOWED_TARGETS` enforces it).
   Apply persists the spec body and flips TRIAGE → READY (or BACKLOG if
   dependencies are unmet); Reject leaves the task in TRIAGE for retry;
   Regenerate is a dry-run that does not touch the store.

10. **LLM Decomposer**: `TaskDecomposer` protocol breaks a TRIAGE task into a
    DAG of child tasks. Returns `DecomposeOutcome` with `fanout` flag — when
    the LLM decides no decomposition is needed, `fanout=False` and the
    outcome carries `new_title`/`new_body`/`new_assignee` so the server
    layer can auto-promote TRIAGE→READY (Specify fallback) without a
    second LLM call. Each `DecomposeChildSpec` carries title,
    body, optional assignee, and `parent_indices` (index-based references
    resolved to real task IDs at persistence time). Apply creates children
    atomically and records a `DECOMPOSED` event on the parent.

11. **Role-scoped tool loading**: `create_kanban_tools(mode=...)` loads tools by role:
    - `worker` (6 tools): kanban_show, kanban_complete, kanban_block, kanban_heartbeat,
      kanban_comment, kanban_attach. Worker tools auto-bind to `current_task_id` via closure and enforce
      ownership — a worker cannot operate on other agents' tasks (prompt injection defense).
      Exception: `kanban_comment` is intentionally unrestricted — workers can comment on
      any task (own or sibling) for cross-task coordination. Comments are consumed by
      `context_builder._gather_comments()` and injected into the worker's context.
      `kanban_complete` sets `metadata.completion_intent=True`, writes `summary` to
      `task.result`, and keeps the task RUNNING until the dispatcher's CompletionVerifier
      passes. Frontend shows `status.verifying` when intent is set. Optional `metadata`
      JSON stores structured handoff at `task.metadata["handoff"]`.
    - `orchestrator` (5 tools): kanban_add_task, kanban_list_tasks (board list or
      single-task read via `task_id`; optional `include_stats`; board list defaults to 50 rows,
      max 200, with `truncated` metadata), kanban_unblock (returns ``dependencies_met``;
      ``waiting_on_dependencies`` when parents remain open), kanban_cancel_task (archives
      READY/BACKLOG/BLOCKED/FAILED tasks; for RUNNING tasks also cancels the worker
      execution via dispatcher; IN_REVIEW tasks are rejected — the approval gate only
      resolves via approve/reject), kanban_retry_task (resets a FAILED task to READY with
      cleared failure counters; optionally updates description for better worker guidance).
    Board/task field edits and delete use server REST/GUI only — not LLM tools.

12. **Dispatcher-only status guard**: Agents cannot move tasks to RUNNING — only the
    dispatcher sets that status when claiming a task. Prevents status drift.

13. **Idempotency key**: `kanban_add_task` accepts an optional `idempotency_key` stored
    in task metadata. Duplicate creations with the same key return the existing task
    instead of creating a new one — makes agent retries safe.

14. **Conditional loading via `enable_kanban` flag**: Default agents do not bind any kanban tools
    (`DEFAULT_ENABLED_BUILTIN_TOOLS` = `web_search` + `memory` only). The server's `profile_resolver`
    maps `"kanban" in enabled_builtin_tools` to `enable_kanban=True`. Binding is
    resolved by `myrm-agent-server/app/ai_agents/general_agent/kanban_tool_mode.py`:
    chat orchestrators default to 5-tool `orchestrator` mode; `KanbanTaskRunner` binds
    6-tool `worker` mode when `kanban_current_task_id` is set; board management uses
    REST/GUI.

15. **Task-level timeout (max_runtime_seconds)**: Each task can declare an optional
    `max_runtime_seconds` limit. The `TaskRunner` enforces this via `asyncio.wait_for`,
    falling back to its own default timeout when the task has no explicit limit. On
    timeout, the runner raises `TaskTimeoutError` (carries `elapsed_seconds` and
    `limit_seconds`). The dispatcher catches `TaskTimeoutError` separately from generic
    `Exception`, emitting `TIMED_OUT` events with audit-grade payload before routing
    through the standard retry/auto-block/fail pipeline with `TaskRunOutcome.TIMED_OUT`.

16. **Task-level skills (extra_skill_ids)**: Each `KanbanTask` carries an optional
    `extra_skill_ids: list[str]` that specifies additional skills the executing agent
    should load for this task only — without modifying the agent profile's global
    `skill_ids`. The `TaskRunner` merges profile skills with task-level skills via
    ordered deduplication (`dict.fromkeys`), preserving profile-first ordering.
    `DecomposeChildSpec` carries `extra_skill_ids: tuple[str, ...]` so decomposers
    can assign specialized skills to individual child tasks (e.g. "translation" for
    a localization subtask). All four input channels are supported: GUI create form,
    REST API (`TaskCreate.extra_skill_ids`), Agent Tool (`kanban_add_task skills=`
    comma-separated), and decompose workflow.

17. **Post-execution status guard (reclaim race protection)**: `_handle_success`,
    `_handle_failure`, and `_handle_timeout` all re-read the task from the store and
    verify `task.status == RUNNING` before writing results. When the agent called
    `kanban_block`, `_handle_failure` finalizes the run as BLOCKED. For all other
    non-RUNNING statuses (e.g. user reclaim during execution), the run is closed as
    `RECLAIMED`. Completion gate: only `_handle_success` + verifier may set COMPLETED;
    stream text alone never completes a task.

18. **Manual reclaim (operator-driven task abort)**: `KanbanDispatcher.reclaim_task(task_id, reason)`
    enables external callers (e.g. REST API, GUI) to immediately cancel a RUNNING task's
    asyncio worker, close the active run as RECLAIMED, reset the task to READY with
    cleared failure counters, and emit a RECLAIMED event with `{manual: true}`. Uses
    `_task_id_to_exec` dict for O(1) task→worker lookup and `asyncio.Task.cancel()` for
    graceful in-process interruption (no SIGTERM/SIGKILL needed). Both `_reclaim_task`
    (automatic zombie reclaim) and `reclaim_task` (manual operator reclaim) cancel the
    active worker before resetting task status, preventing duplicate execution when a
    task is reclaimed while its worker is still alive.

19. **Worker Lifecycle Guidance Injection**: `get_worker_lifecycle_guidance()` is a pure
    function that generates concise operational instructions for kanban worker agents.
    Injected by the server's agent factory into the system prompt when `kanban_tool_mode="worker"`.
    Covers: mandatory complete/block termination, heartbeat cadence (dynamically parameterized
    based on `zombie_timeout_seconds`), retry diagnosis awareness, completion metadata,
    cross-task comments, and file attachment guidance for produced deliverables.
    Prevents tasks from getting stuck due to agents not knowing the lifecycle protocol.

20. **Task-level workspace / worktree isolation**: Each `KanbanTask` carries optional
    `workspace_path` and `branch` fields. `BoardSettings.default_workdir` provides a
    board-level default. The server's `TaskRunner._resolve_workspace()` resolves the
    effective workspace (task-level > board-level default). When `branch` is set, the
    runner calls `_create_worktree()` which executes `git worktree add` to create an
    isolated checkout under `<workspace>/.worktrees/<task_id>-<branch>`. The resolved
    workspace is passed to `GeneralAgentParams.declared_allowed_roots`, binding the
    agent's file operations to the worktree. A `BRANCH_SWITCHED` event is emitted
    only when the worktree is newly created (not on repeat resolutions, so frequent
    resolutions such as per-attach calls stay event-silent). On task archive, `cleanup_worktree()`
    runs `git worktree remove` to reclaim disk. This enables conflict-free parallel
    coding by multiple agents on the same repository.

21. **Transient error smart backoff**: When `_apply_failure_pipeline` encounters a
    retriable error matching `_TRANSIENT_ERROR_RE` (429 rate-limit, 503 service
    unavailable, quota exceeded, capacity overloaded), the task is moved to
    `BLOCKED` with `block_kind=SCHEDULED` and `scheduled_until` set to
    `now + 15 minutes` instead of immediately re-queuing as READY. The existing
    `_wakeup_scheduled_tasks` mechanism in the zombie loop auto-unblocks the task
    when the backoff period expires, resetting `consecutive_failures` to 0. This
    prevents the dispatcher from exhausting the retry budget on errors that cannot
    resolve instantly (API quota resets on a timer, maintenance windows end
    naturally), eliminating unnecessary human intervention for auto-blocked tasks.
    The `auto_block_after_consecutive_failures` threshold still takes priority —
    if the task has already exceeded the threshold, it auto-blocks as HUMAN
    regardless of the transient pattern.

22. **Startup orphan rescue**: `_rescue_orphaned_tasks()` runs once during
    `start()` before the dispatch/zombie loops begin. It queries
    `list_running_tasks` for the board and reclaims every task that has no
    active execution handle in `_task_id_to_exec` — i.e. tasks left in
    RUNNING state by a prior process crash. Uses the same `_reclaim_task`
    pipeline (retry budget check → auto-block → fail → event/emit) so
    behaviour is identical to zombie detection, just immediate (< 1 s vs
    60–120 s zombie timeout). On `InMemoryKanbanStore` this is a harmless
    no-op (data lost on restart); on persistent stores (e.g.
    `SqlAlchemyKanbanStore`) it eliminates the post-restart "ghost RUNNING"
    window entirely.

23. **Goal Loop Mode (goal_mode)**: Each `KanbanTask` carries optional `goal_mode: bool`
    (default False) and `goal_max_turns: int | None` fields. When `goal_mode=True`, the
    server's `TaskRunner` creates a `GoalProvider` (via `GoalRegistry`) and injects it
    into the agent's `runtime_context`, enabling the harness `StreamExecutor` to drive
    autonomous multi-turn execution until the objective is semantically met or the
    budget is exhausted. The existing Goal infrastructure (4-dim budget, semantic judge,
    convergence detection, WAIT state, acceptance criteria verification) is fully reused
    — zero harness-layer changes required. Goal terminal status maps to Kanban outcomes:
    `COMPLETE` → task success, `BUDGET_LIMITED` → task failure with budget info,
    `PAUSED/NEEDS_HUMAN_REVIEW` → task failure with pause reason. The `GoalProvider`
    is unregistered from `GoalRegistry` in the runner's `finally` block to prevent leaks.

24. **Per-task model override (model_override)**: Each `KanbanTask` carries an optional
    `model_override: str | None` field in `'provider/model'` LiteLLM form. When set, the
    server `TaskRunner` resolves this model for the task instead of the agent profile
    default — enabling task-level cost governance and model specialization. Child tasks
    created via decomposition inherit the parent's override unless they specify their own.
    The `kanban_add_task` orchestrator tool accepts a `model` parameter; the API layer
    validates overrides against enabled providers (400 on unresolvable models) to prevent
    silent runtime fallback.

25. **Human approval gate (require_approval → IN_REVIEW)**: Each `KanbanTask` carries an
    optional `require_approval: bool = False`. When a `require_approval` task's run passes
    verification, `_handle_success` routes it to `IN_REVIEW` instead of `COMPLETED` and
    emits `REVIEW_REQUESTED`. `approve_task(task_id, approver)` promotes `IN_REVIEW` →
    `COMPLETED` (clears failure counters, records `APPROVED` event, promotes dependents);
    `reject_task(task_id, reason, approver)` returns the task to `READY` with the reason
    echoed into `task.error`, resets `retry_count`/`consecutive_failures` so rework gets a
    fresh budget, and records a `REJECTED` event. Both are operator-driven (REST/GUI only —
    no LLM tool) and idempotent no-ops when the task is not `IN_REVIEW`. Both transitions
    use the store's atomic `transition_task_status` CAS (`expected_status` guard), so
    concurrent approve/reject calls resolve exactly once and loser calls observe the
    post-transition state without emitting duplicate events. Rejected reasons surface in
    the worker context under `## Review history` (via `context_builder`). `task.error` is
    cleared on any verified success path (IN_REVIEW or COMPLETED) to match the `reclaim`
    semantics — a task that is successfully re-submitted never carries a stale rejection
    reason. The flag is mutable while the task is active (server-side `update_task` guards
    the edit: TRIAGE/BACKLOG/READY/RUNNING/BLOCKED may toggle it, while IN_REVIEW and
    terminal states reject the change) — the harness never mutates `require_approval`
    post-creation, so the guard lives in the business layer only.

26. **Runtime board hot-swap (refresh_board)**: `KanbanDispatcher.refresh_board(board)`
    replaces the dispatcher's board reference in place (rejects mismatched board_id).
    The dispatch loop, zombie loop, and per-task heartbeat loop all re-read
    `self._board.settings` on every cycle, so edits to `max_concurrent_tasks`,
    `zombie_timeout_seconds`, and `heartbeat_interval_seconds` take effect on the next
    wake cycle while already-executing tasks keep running untouched — no dispatcher
    restart required. The server's `update_board` calls this whenever board settings
    change, so the live scheduler and the persisted config never diverge (the GUI's
    concurrency badge reflects what the dispatcher actually enforces).

## Domain Model

- `KanbanBoard`: Top-level grouping with `BoardSettings` (includes `default_workdir`, `block_recurrence_limit` for block→unblock→TRIAGE escalation)
- `KanbanTask`: Unit of work with 9-state lifecycle (TRIAGE → BACKLOG → READY → RUNNING → COMPLETED/FAILED/BLOCKED/ARCHIVED, plus IN_REVIEW on the verified-success path of `require_approval` tasks), with `block_kind` (HUMAN/SCHEDULED/EXTERNAL) and `scheduled_until` for semantic blocking, `block_cycle_count` for detecting block→unblock cycling, `attachments: list[TaskAttachment]` for multimodal file references, `workspace_path` and `branch` for worktree isolation, `goal_mode` and `goal_max_turns` for autonomous multi-turn goal loop execution, `model_override: str | None` for per-task LLM selection overriding the agent profile default, and `require_approval: bool` for the human approval gate
- `TaskAttachment`: Immutable file attachment (file_id, filename, mime_type, size_bytes, content_ref) with polymorphic content_ref (HTTP URL / vault pointer / inline data)
- `BlockKind`: Sub-type enum for BLOCKED tasks (HUMAN / SCHEDULED / EXTERNAL)
- `TaskEdge`: Directed dependency edge (parent→child), forms a DAG with cycle rejection
- `TaskClaim`: Worker ownership record
- `TaskPriority`: URGENT > HIGH > NORMAL > LOW
- `TaskRun`: Independent record per execution attempt (run_id, worker_id, outcome, duration)
- `TaskRunOutcome`: COMPLETED / BLOCKED / CRASHED / RECLAIMED / TIMED_OUT
- `TaskEvent`: Persistent lifecycle event for audit and catch-up
- `TaskEventKind`: CREATED / CLAIMED / ASSIGNED / COMPLETED / FAILED / BLOCKED / UNBLOCKED / RETRYING / RECLAIMED / PROMOTED / ARCHIVED / HEARTBEAT / USER_COMMENT / VERIFICATION_FAILED / BRANCH_SWITCHED / SPECIFIED / DECOMPOSED / TIMED_OUT / REVIEW_REQUESTED / APPROVED / REJECTED
- `TaskTimeoutError`: Exception raised when a task exceeds its `max_runtime_seconds` limit (carries `elapsed_seconds`, `limit_seconds`)
- `SpecifyOutcome`: Result of a single Specifier pass (ok, new_title, new_body, reason, prompt_tokens, completion_tokens, persisted)
- `DecomposeChildSpec`: Spec for a single child task (title, body, assignee, parent_indices)
- `DecomposeOutcome`: Result of a Decomposer pass (ok, fanout, children, rationale, tokens, persisted, child_ids, new_title, new_body, new_assignee)

## File Inventory

| File | POS |
|------|-----|
| `types.py` | Pure domain types (Board, Task, Status, Priority, Settings, Run, Event) |
| `protocols.py` | KanbanStore (CRUD + edges + runs + events + `transition_task_status` 原子 CAS) + TaskRunner + CompletionVerifier + TaskSpecifier + TaskDecomposer protocol contracts |
| `stores.py` | InMemoryKanbanStore (test/reference, with DFS cycle detection) |
| `dispatcher.py` | Event-driven scheduler — dispatch loop, task execution, completion verification, dependency promotion, event emission |
| `dispatcher_failure.py` | Failure/timeout/retry pipeline mixin for KanbanDispatcher |
| `dispatcher_zombie.py` | Zombie detection, heartbeat monitoring, scheduled wakeup, and startup orphan rescue mixin |
| `diagnostics.py` | Task diagnostic framework — DTOs, DiagnosticRule Protocol, DiagnosticEngine |
| `kanban_agent_tools.py` | Facade — `create_kanban_tools` factory, shared helpers (`_parse_until`, `get_worker_lifecycle_guidance`), routes to worker/orchestrator sub-modules |
| `_worker_tools.py` | Worker-scoped LLM tools (6 tools: show/complete/block/heartbeat/comment/attach) with ownership enforcement |
| `_orchestrator_tools.py` | Orchestrator-scoped LLM tools (5 tools: add_task/list_tasks/unblock/cancel_task/retry_task) for task lifecycle management |
| `context_builder.py` | Worker context assembly helper for TaskRunner implementors — includes parent result + handoff metadata propagation + `build_multimodal_query()` for assembling TaskAttachment objects into LLM-compatible multimodal content blocks |
| `__init__.py` | Public API re-exports |
