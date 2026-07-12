"""Context pipeline middleware.

 Self-update reminder: once this file is updated, also update:
1. agent/context_management/PROMPT_CACHE_PRACTICE.md §5 Pipeline

Unified Pipeline architecture for context management (filter, compress, Session Notes,
summarize, explicit cache). Supports summary persistence callback: after the Pipeline
produces a StructuredSummary, the on_summary_persist callback asynchronously notifies
the business layer for DB persistence.

Capabilities:
- Filter: large tool result truncation + smart preview (in-memory)
- Cache TTL prune / Compress: old tool results are trimmed or offloaded before
  compaction (Manus "lossy but traceable" principle)
- Session Notes: real-time structured notes, zero-API-call compression substitute;
  DB persistence + lazy loading
- Summarize: structured summary for oversized contexts (irreversible, Session Notes fallback)
- Explicit Cache: inject cache_control markers for Claude/Qwen (auto-detected)
- Summary persistence bridge: passes summaries to business layer via SummaryPersistCallback
- Archive checkpoint bridge: optional `ArchiveCheckpointStore` + notifier wired into `ArchiveSummaryService`

Usage:
    from myrm_agent_harness.agent.middlewares import create_context_pipeline_middleware

    agent = SkillAgent(
        llm=llm,
        middlewares=[create_context_pipeline_middleware(llm, on_summary_persist=my_callback)])

[INPUT]
- agent.context_management.archive_checkpoint::ArchiveSummaryService, ArchiveCheckpointStore (POS: Lite-LLM archive summary checkpoints for pruned tool outputs.)
- agent.context_management.pipeline::ContextPipeline, (POS: Message filter pipeline for composing multiple filters.)
- agent.context_management.strategies.session_notes.updater::NotesLoadCallback, (POS: Session Notes callback)
- middlewares.context_pipeline_helpers::* (POS: Helper layer for context pipeline middleware. Keeps request metadata parsing and tool schema fingerprinting separate from middleware orchestration.)

[OUTPUT]
- create_context_pipeline_middleware: Context pipeline middleware factory

[POS]
Provides create_context_pipeline_middleware.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import cast

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, BaseMessage

from myrm_agent_harness.agent.context_management.archive_checkpoint import (
    ArchiveCheckpointStore,
    ArchiveSummaryService,
)
from myrm_agent_harness.agent.context_management.archive_checkpoint.summary_service import (
    ArchiveCheckpointNotifier,
)
from myrm_agent_harness.agent.context_management.context import (
    extract_context_from_request,
)
from myrm_agent_harness.agent.context_management.infra.cache_break_detector import (
    get_cache_break_detector,
)
from myrm_agent_harness.agent.context_management.infra.cache_metrics_collector import (
    clear_pending_explicit_cache_snapshot,
)
from myrm_agent_harness.agent.context_management.infra.cache_policy import (
    resolve_cache_ttl_prune_policy,
)
from myrm_agent_harness.agent.context_management.infra.schemas import (
    CacheTtlPruneConfig,
    ContextCompressEvictionCallback,
    ContextCompressOffloadCallback,
    ContextPreCompactCallback,
    ContextSnapshotCallback,
    SummaryPersistCallback,
)
from myrm_agent_harness.agent.context_management.infra.session_lock import (
    acquire_context_lock,
)
from myrm_agent_harness.agent.context_management.pipeline import (
    ContextPipeline,
    ProcessorContext,
    build_default_processors,
)
from myrm_agent_harness.agent.context_management.strategies.integrity_guard import (
    ensure_tool_pair_integrity,
)
from myrm_agent_harness.agent.context_management.strategies.session_notes.updater import (
    NotesLoadCallback,
    NotesPersistCallback,
    SessionNotesManager,
)
from myrm_agent_harness.agent.context_management.tracking.task_metrics import (
    get_or_create_task_metrics,
)
from myrm_agent_harness.agent.middlewares.context_pipeline_helpers import (
    extract_compression_intent,
    extract_tool_names_and_schemas,
    resolve_cache_usage_feedback,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.token_estimation import (
    estimate_messages_tokens,
)

logger = get_agent_logger(__name__)


def create_context_pipeline_middleware(
    llm: BaseChatModel,
    user_id: str = "unknown",
    pipeline: ContextPipeline | None = None,
    tool_result_evict_threshold: int = 5000,
    compress_min_save: int = 3000,
    compress_batch_rounds: int = 5,
    keep_recent_calls: int = 5,
    tail_budget_ratio: float = 0.20,
    on_summary_persist: SummaryPersistCallback | None = None,
    on_compress_offload: ContextCompressOffloadCallback | None = None,
    on_compress_eviction: ContextCompressEvictionCallback | None = None,
    on_context_snapshot: ContextSnapshotCallback | None = None,
    on_pre_compact: ContextPreCompactCallback | None = None,
    summarizer_llm: BaseChatModel | None = None,
    archive_checkpoint_store: ArchiveCheckpointStore | None = None,
    on_archive_checkpoint: ArchiveCheckpointNotifier | None = None,
    session_notes_llm: BaseChatModel | None = None,
    on_notes_persist: NotesPersistCallback | None = None,
    on_notes_load: NotesLoadCallback | None = None,
    budget_pressure_fn: Callable[[], bool] | None = None,
    time_decay_half_life_days: float | None = None,
    cache_ttl_prune_config: CacheTtlPruneConfig | None = None,
) -> AgentMiddleware:
    """Create the context pipeline middleware.

    Capabilities:
    1. Context management (filter, compress, Session Notes, summarize, explicit cache)
    2. Built-in file_read_tool (provided via get_tools attribute)
    3. Summary persistence bridge (via on_summary_persist callback)
    4. Session Notes DB persistence (via on_notes_persist / on_notes_load callbacks)
    5. Eco mode signal injection (via budget_pressure_fn callback)

    Args:
        llm: LLM client (used by processors that need LLM, e.g. filter and summarize)
        pipeline: Custom pipeline (optional)
        tool_result_evict_threshold: Tool result eviction threshold (default 5000 tokens)
        compress_min_save: Minimum compression savings threshold (default 3000 tokens)
        compress_batch_rounds: Batch compression accumulation rounds (default 5)
        keep_recent_calls: Recent tool calls to keep in full format (default 5)
        on_summary_persist: Summary persistence callback (optional). Without it the pipeline
                           works in-memory only; with it summaries are async-written to DB.
        on_compress_offload: Tool result offload callback for cache pruning and compression (recommended).
                            Business layer implements via CodeExecutor, following the
                            "lossy but traceable" principle.
        on_context_snapshot: Pre-compression full message snapshot callback (optional).
                            Serializes complete conversation to sanitized+gzip JSONL for audit.
        session_notes_llm: Lightweight LLM for Session Notes background updates (optional).
                          When provided, enables Session Notes (real-time notes + zero-API compression).
                          Recommend a cheap model (e.g. GPT-4o-mini / Claude Haiku).
        on_notes_persist: Session Notes persistence callback (optional). Async-writes after each update.
        on_notes_load: Session Notes load callback (optional). Lazy-loads from DB on first call.
        budget_pressure_fn: Budget pressure detection callback (optional). When True,
                           activates Eco mode — CompressProcessor triggers earlier and reduces
                           keep_recent_calls. Business layer injects; framework is budget-agnostic.

    Returns:
        Middleware function (with get_tools and session_notes_manager attributes)
    """
    _pipelines: dict[tuple[int | None, str], ContextPipeline] = {}
    _custom_pipeline = pipeline
    _notes_loaded = False
    _last_successful_call_time: float = 0.0
    _summary_persist_tasks: set[asyncio.Task[None]] = set()

    _notes_manager: SessionNotesManager | None = None
    if session_notes_llm is not None:
        _notes_manager = SessionNotesManager(llm=session_notes_llm, on_persist=on_notes_persist)

    def _get_or_create_pipeline(
        max_context_tokens: int | None,
        model_name: str,
        compress_start_ratio: float | None = None,
    ) -> ContextPipeline:
        if _custom_pipeline:
            return _custom_pipeline

        key = (max_context_tokens, model_name)
        if key not in _pipelines:
            actual_max_tokens = max_context_tokens or 128000
            cache_policy = resolve_cache_ttl_prune_policy(
                model_name,
                override=cache_ttl_prune_config,
            )
            archive_summary_service: ArchiveSummaryService | None = None
            if archive_checkpoint_store is not None:
                archive_summary_service = ArchiveSummaryService(
                    config=cache_policy.config,
                    store=archive_checkpoint_store,
                    on_checkpoint=on_archive_checkpoint,
                )

            processors = build_default_processors(
                max_context_tokens=actual_max_tokens,
                compress_start_ratio=compress_start_ratio,
                tool_result_evict_threshold=tool_result_evict_threshold,
                compress_min_save=compress_min_save,
                compress_batch_rounds=compress_batch_rounds,
                keep_recent_calls=keep_recent_calls,
                tail_budget_ratio=tail_budget_ratio,
                on_compress_offload=on_compress_offload,
                on_compress_eviction=on_compress_eviction,
                on_context_snapshot=on_context_snapshot,
                on_pre_compact=on_pre_compact,
                archive_summary_service=archive_summary_service,
                session_notes_manager=_notes_manager,
                time_decay_half_life_days=time_decay_half_life_days,
                cache_ttl_prune_config=cache_policy.config,
            )

            _pipelines[key] = ContextPipeline(processors)
            if max_context_tokens:
                notes_status = "enabled" if _notes_manager else "disabled"
                logger.info(
                    "Created dynamic pipeline: max_context_tokens=%d, session_notes=%s, cache_policy=%s",
                    max_context_tokens,
                    notes_status,
                    cache_policy.model_family,
                )

        return _pipelines[key]

    class ContextPipelineMiddleware(AgentMiddleware):
        """Pipeline middleware (Session Notes + summary persistence bridge)."""

        name = "context_pipeline_middleware"

        async def awrap_model_call(
            self,
            request: ModelRequest,
            handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
        ) -> ModelResponse:
            nonlocal _notes_loaded, _last_successful_call_time

            messages = cast(list[BaseMessage], list(request.messages))

            chat_id, max_context_tokens, compress_start_ratio = extract_context_from_request(request)

            model_name = getattr(llm, "model", None) or getattr(llm, "model_name", "")
            model_name_str = str(model_name)
            current_pipeline = _get_or_create_pipeline(max_context_tokens, model_name_str, compress_start_ratio)
            turn_count = sum(1 for m in messages if m.type == "human")
            total_tokens = estimate_messages_tokens(messages)
            metrics = get_or_create_task_metrics(chat_id)
            if metrics is not None:
                metrics.add_input_tokens(total_tokens)

            last_message_db_id = _extract_last_message_db_id(request)

            if _notes_manager is not None:
                if not _notes_loaded and on_notes_load is not None:
                    _notes_loaded = True
                    try:
                        notes_json = await on_notes_load()
                        if notes_json:
                            _notes_manager.load_from_json(notes_json)
                    except Exception as exc:
                        logger.warning(
                            "[SessionNotes] DB load failed: %s: %s",
                            type(exc).__name__,
                            exc,
                        )

                total_tool_calls = _count_tool_calls(messages)
                await _notes_manager.maybe_trigger_update(messages, total_tokens, total_tool_calls)

            async with acquire_context_lock(chat_id):
                clear_pending_explicit_cache_snapshot()

                # Extract merged_context from request for Prompt Cache preservation flags
                runtime_context = getattr(request.runtime, "context", {}) if hasattr(request, "runtime") else {}
                merged_ctx = runtime_context if isinstance(runtime_context, dict) else {}
                is_resume = merged_ctx.get("is_resume", False)

            # Context overflow check for Resume (prevent cache-breaking retry)
            if is_resume and max_context_tokens is not None and total_tokens > max_context_tokens:
                logger.error(
                    "[Resume] Context overflow detected: %d / %d tokens. "
                    "Cannot resume without breaking Prompt Cache. "
                    "Consider clearing conversation history or enabling offload.",
                    total_tokens,
                    max_context_tokens,
                )
                raise ValueError(
                    f"Resume failed: context overflow ({total_tokens}/{max_context_tokens} tokens). "
                    f"History too large to resume without compression."
                )

            # Eco mode: query business layer for budget pressure
            eco_mode = False
            if budget_pressure_fn is not None:
                try:
                    eco_mode = budget_pressure_fn()
                except Exception as exc:
                    logger.debug("budget_pressure_fn failed (non-blocking): %s", exc)

            context = ProcessorContext(
                messages=messages,
                user_query="",
                user_id=merged_ctx.get("user_id"),
                chat_id=chat_id,
                llm=llm,
                summarizer_llm=summarizer_llm or llm,
                is_resume=is_resume,
                merged_context=merged_ctx,
                metadata={
                    "model_name": model_name,
                    "base_url": getattr(llm, "api_base", "") or "",
                    "turn_count": turn_count,
                    "last_message_db_id": last_message_db_id,
                    "compression_intent": extract_compression_intent(merged_ctx),
                    "eco_mode": eco_mode,
                    "supports_vision": merged_ctx.get("supports_vision", True),
                    "last_activity_time": _last_successful_call_time or None,
                    "cache_usage_feedback": resolve_cache_usage_feedback(merged_ctx),
                    "runnable_config": getattr(request, "config", None),
                },
            )

            result = await current_pipeline.process(context)
            guarded_messages = ensure_tool_pair_integrity(result.messages)
            if guarded_messages is not result.messages:
                result.messages = guarded_messages
                result.operations.append("integrity_guard")

            if "summarize" in result.operations:
                from myrm_agent_harness.utils.event_utils import dispatch_custom_event

                try:
                    await dispatch_custom_event(
                        "agent_status",
                        {
                            "step_key": "memory_archived",
                            "message": "Early history archived",
                            "tokens_saved": result.tokens_saved,
                        },
                        config=getattr(request, "config", None),
                    )
                except Exception as e:
                    logger.debug("Failed to dispatch agent_status event: %s", e)

            if "cache_ttl_prune" in result.operations:
                from myrm_agent_harness.utils.event_utils import dispatch_custom_event

                try:
                    await dispatch_custom_event(
                        "agent_status",
                        {
                            "step_key": "context_pruned",
                            "message": "Expired context pruned",
                            "tokens_saved": result.tokens_saved,
                        },
                        config=getattr(request, "config", None),
                    )
                except Exception as e:
                    logger.debug("Failed to dispatch cache pruning status event: %s", e)

            if result.tokens_saved > 0 or result.messages is not messages:
                request = request.override(messages=cast(list[AnyMessage], result.messages))

                # Reset read-before-edit gate when context is compressed/summarized,
                # because the model no longer has byte-level visibility of previously
                # read file contents — it must re-read before editing.
                if result.tokens_saved > 0:
                    from myrm_agent_harness.agent.meta_tools.file_ops.core.staleness_guard import (
                        _staleness_guards,
                    )

                    for guard in _staleness_guards.values():
                        guard.clear()

                    from myrm_agent_harness.agent.middlewares.tool_interceptor_middleware import (
                        notify_loop_guard_compaction,
                    )

                    notify_loop_guard_compaction()

            detector = get_cache_break_detector()
            if detector is not None:
                detector.record_prompt_state(
                    messages=result.messages,
                    model=str(model_name),
                    tool_names_and_schemas=extract_tool_names_and_schemas(request),
                )

            if on_summary_persist is not None and result.structured_summary is not None and chat_id:
                persist_task = asyncio.create_task(_safe_persist_summary(on_summary_persist, chat_id, result))
                _summary_persist_tasks.add(persist_task)
                persist_task.add_done_callback(_summary_persist_tasks.discard)

            response = await handler(request)
            _last_successful_call_time = time.time()
            return response

    context_pipeline_middleware = ContextPipelineMiddleware()

    def get_tools() -> list[object]:
        from myrm_agent_harness.agent.meta_tools import create_file_read_tool

        file_read_tool = create_file_read_tool(skills=[])
        logger.info("file_read_tool provided by context pipeline middleware")
        return [file_read_tool]

    context_pipeline_middleware.get_tools = get_tools  # type: ignore[attr-defined]
    context_pipeline_middleware.session_notes_manager = _notes_manager  # type: ignore[attr-defined]

    return context_pipeline_middleware


def _count_tool_calls(messages: list[BaseMessage]) -> int:
    """Count total tool calls across all messages."""
    count = 0
    for msg in messages:
        if msg.type == "ai" and hasattr(msg, "tool_calls") and msg.tool_calls:
            count += len(msg.tool_calls)
    return count


def _extract_last_message_db_id(request: ModelRequest) -> str | None:
    """Extract last message DB ID from runtime.context."""
    try:
        if not hasattr(request, "runtime") or not request.runtime:
            return None
        context = getattr(request.runtime, "context", None)
        if isinstance(context, dict):
            val = context.get("last_message_db_id")
        else:
            val = getattr(context, "last_message_db_id", None)
        return str(val) if val is not None else None
    except Exception:
        return None


async def _safe_persist_summary(callback: SummaryPersistCallback, chat_id: str, result: ProcessorContext) -> None:
    """Safely invoke summary persist callback (fire-and-forget, non-blocking)."""
    try:
        await callback(
            chat_id=chat_id,
            summary=result.structured_summary,  # type: ignore[arg-type]
            before_message_id=result.last_summarized_message_id or "",
            tokens_saved=result.tokens_saved,
        )
        logger.info(
            "[SummaryPersist] Summary persisted: chat_id=%s, tokens_saved=%d",
            chat_id,
            result.tokens_saved,
        )
    except Exception as exc:
        logger.error("[SummaryPersist] Persist failed: %s", exc)
