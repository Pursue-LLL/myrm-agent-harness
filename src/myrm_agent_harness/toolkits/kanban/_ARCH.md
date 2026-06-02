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
   heartbeats. The zombie loop reclaims tasks whose heartbeat exceeds `zombie_timeout_seconds`.
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

5. **Goal integration**: Tasks can optionally link to a `goal_id`, allowing
   complex tasks to leverage the existing Goal Guard Chain for execution.

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
    - `worker` (5 tools): kanban_show, kanban_complete, kanban_block, kanban_heartbeat,
      kanban_comment. Worker tools auto-bind to `current_task_id` via closure and enforce
      ownership — a worker cannot operate on other agents' tasks (prompt injection defense).
      Exception: `kanban_comment` is intentionally unrestricted — workers can comment on
      any task (own or sibling) for cross-task coordination. Comments are consumed by
      `context_builder._gather_comments()` and injected into the worker's context.
      `kanban_complete` writes `summary` to `task.result` for downstream context
      propagation, and accepts optional `metadata` JSON for structured machine-readable
      handoff data stored at `task.metadata["handoff"]`.
    - `orchestrator` (8 tools): kanban_add_task, kanban_list_tasks, kanban_update_task,
      kanban_move_task, kanban_delete_task, kanban_board_summary, kanban_add_dependency,
      kanban_remove_dependency.
    - `full` (16 tools): All worker + orchestrator + kanban_create_board, kanban_list_boards,
      kanban_get_task.

12. **Dispatcher-only status guard**: Agents cannot move tasks to RUNNING — only the
    dispatcher sets that status when claiming a task. Prevents status drift.

13. **Idempotency key**: `kanban_add_task` accepts an optional `idempotency_key` stored
    in task metadata. Duplicate creations with the same key return the existing task
    instead of creating a new one — makes agent retries safe.

14. **Conditional loading via `enable_kanban` flag**: The server's `profile_resolver`
    maps `"kanban" in enabled_builtin_tools` to `enable_kanban=True`. Only agents
    configured with kanban capability receive these tools, preventing schema bloat in
    general chat sessions. Worker tools are auto-injected for `KanbanTaskRunner` tasks.

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
    verify `task.status == RUNNING` before writing results. Special case: when
    `_handle_success` finds `task.status == COMPLETED` (agent called `kanban_complete`
    tool during execution), it finalizes the run as COMPLETED and triggers
    `_promote_dependents` — ensuring downstream DAG tasks are correctly unlocked.
    For all other non-RUNNING statuses (e.g. user reclaim during execution), the run
    is closed as `RECLAIMED`. This prevents a race condition where a user reclaims a
    task but the old runner's late completion overwrites the reclaim.

18. **Manual reclaim (operator-driven task abort)**: `KanbanDispatcher.reclaim_task(task_id, reason)`
    enables external callers (e.g. REST API, GUI) to immediately cancel a RUNNING task's
    asyncio worker, close the active run as RECLAIMED, reset the task to READY with
    cleared failure counters, and emit a RECLAIMED event with `{manual: true}`. Uses
    `_task_id_to_exec` dict for O(1) task→worker lookup and `asyncio.Task.cancel()` for
    graceful in-process interruption (no SIGTERM/SIGKILL needed). The zombie detector's
    `_reclaim_task` handles automatic heartbeat-timeout reclaims; manual reclaim handles
    operator-initiated aborts.

19. **Worker Lifecycle Guidance Injection**: `get_worker_lifecycle_guidance()` is a pure
    function that generates concise operational instructions for kanban worker agents.
    Injected by the server's agent factory into the system prompt when `kanban_tool_mode="worker"`.
    Covers: mandatory complete/block termination, heartbeat cadence (dynamically parameterized
    based on `zombie_timeout_seconds`), retry diagnosis awareness, and completion metadata.
    Prevents tasks from getting stuck due to agents not knowing the lifecycle protocol.

20. **Task-level workspace / worktree isolation**: Each `KanbanTask` carries optional
    `workspace_path` and `branch` fields. `BoardSettings.default_workdir` provides a
    board-level default. The server's `TaskRunner._resolve_workspace()` resolves the
    effective workspace (task-level > board-level default). When `branch` is set, the
    runner calls `_create_worktree()` which executes `git worktree add` to create an
    isolated checkout under `<workspace>/.worktrees/<task_id>-<branch>`. The resolved
    workspace is passed to `GeneralAgentParams.declared_allowed_roots`, binding the
    agent's file operations to the worktree. On task archive, `cleanup_worktree()`
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

## Domain Model

- `KanbanBoard`: Top-level grouping with `BoardSettings` (includes `default_workdir` for board-level workspace default)
- `KanbanTask`: Unit of work with 8-state lifecycle (TRIAGE → BACKLOG → READY → RUNNING → COMPLETED/FAILED/BLOCKED/ARCHIVED), with `block_kind` (HUMAN/SCHEDULED/EXTERNAL) and `scheduled_until` for semantic blocking, `block_cycle_count` for detecting block→unblock cycling, `attachments: list[TaskAttachment]` for multimodal file references, `workspace_path` and `branch` for worktree isolation
- `TaskAttachment`: Immutable file attachment (file_id, filename, mime_type, size_bytes, content_ref) with polymorphic content_ref (HTTP URL / vault pointer / inline data)
- `BlockKind`: Sub-type enum for BLOCKED tasks (HUMAN / SCHEDULED / EXTERNAL)
- `TaskEdge`: Directed dependency edge (parent→child), forms a DAG with cycle rejection
- `TaskClaim`: Worker ownership record
- `TaskPriority`: URGENT > HIGH > NORMAL > LOW
- `TaskRun`: Independent record per execution attempt (run_id, worker_id, outcome, duration)
- `TaskRunOutcome`: COMPLETED / BLOCKED / CRASHED / RECLAIMED / TIMED_OUT
- `TaskEvent`: Persistent lifecycle event for audit and catch-up
- `TaskEventKind`: CREATED / CLAIMED / ASSIGNED / COMPLETED / FAILED / BLOCKED / UNBLOCKED / RETRYING / RECLAIMED / PROMOTED / ARCHIVED / HEARTBEAT / USER_COMMENT / VERIFICATION_FAILED / BRANCH_SWITCHED / SPECIFIED / DECOMPOSED / TIMED_OUT
- `TaskTimeoutError`: Exception raised when a task exceeds its `max_runtime_seconds` limit (carries `elapsed_seconds`, `limit_seconds`)
- `SpecifyOutcome`: Result of a single Specifier pass (ok, new_title, new_body, reason, prompt_tokens, completion_tokens, persisted)
- `DecomposeChildSpec`: Spec for a single child task (title, body, assignee, parent_indices)
- `DecomposeOutcome`: Result of a Decomposer pass (ok, fanout, children, rationale, tokens, persisted, child_ids, new_title, new_body, new_assignee)

## File Inventory

| File | POS |
|------|-----|
| `types.py` | Pure domain types (Board, Task, Status, Priority, Settings, Run, Event) |
| `protocols.py` | KanbanStore (CRUD + edges + runs + events) + TaskRunner + CompletionVerifier + TaskSpecifier + TaskDecomposer protocol contracts |
| `stores.py` | InMemoryKanbanStore (test/reference, with DFS cycle detection) |
| `dispatcher.py` | Event-driven scheduler with heartbeat/zombie/auto-block/transient error smart backoff/run tracking/dependency promotion/pre-and-post-execution status drift guard |
| `diagnostics.py` | Task diagnostic framework — DTOs (TaskDiagnostic, DiagnosticAction, Severity), DiagnosticRule Protocol, DiagnosticEngine. Server layer implements 6 concrete rules including BlockUnblockCyclingRule for detecting block→unblock cycling |
| `kanban_agent_tools.py` | Modular per-action kanban tools with role-scoped loading (worker/orchestrator/full) + `get_worker_lifecycle_guidance()` for system prompt injection |
| `context_builder.py` | Worker context assembly helper for TaskRunner implementors — includes parent result + handoff metadata propagation + `build_multimodal_query()` for assembling TaskAttachment objects into LLM-compatible multimodal content blocks |
| `__init__.py` | Public API re-exports |
