"""Summarize processor (fallback when SessionNotes is unavailable).

When SessionNotesProcessor is not enabled or notes are not ready, serves as a
degraded fallback to generate LLM-based summaries. Summary results are exposed
via context.structured_summary for Middleware to bridge to business-layer persistence.
Pure in-memory operation, no filesystem dependency.

Pipeline order: Filter -> Compress -> SessionNotes -> **SummarizeProcessor** -> ExplicitCache

Design:
1. Summary is based on complete data (not post-compression compact format)
2. Keep N most recent complete calls (so the model knows where it left off)
3. Use structured schema (not free-form, ensures stable output)
4. Support incremental merge (detect existing summary marker, pass existing_summary)
5. Quality audit + retry (ensure critical entities are preserved)
6. Circuit breaker with half-open recovery: degrade to deterministic fallback after
   consecutive failures, probe LLM recovery every N fallback calls
7. Dual compression protection: auto-skip when SessionNotesProcessor already handled
8. Deterministic fallback: builds minimal summary without LLM, ensures agent never deadlocks
9. Anti-consecutive-summarize: skip one API token check after summarization to prevent
   stale API values from triggering an infinite loop
10. Cold Cache Drain Architecture: bypass when cache is hot to protect Prompt Cache

[INPUT]
- agent.context_management.infra.schemas::DEFAULT_CONTEXT_CONFIG (POS: Planner Schema Definitions)

[OUTPUT]
- SummarizeProcessor: class — Summarize Processor

[POS]
Provides SummarizeProcessor.
"""

from __future__ import annotations

import re
import time

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from myrm_agent_harness.observability.metrics.circuit_breaker_metrics import (
    circuit_breaker_failures_total,
    circuit_breaker_state,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.token_estimation import estimate_messages_tokens

from ...infra.schemas import ContextConfig, StructuredSummary
from ...strategies.summarizer import generate_structured_summary, should_summarize
from ...strategies.summary_builder import (
    create_summary_message,
    extract_recent_messages,
)
from ..base import BaseProcessor, ProcessorContext

logger = get_agent_logger(__name__)

MAX_CONSECUTIVE_SUMMARIZE_FAILURES = 3
_HALF_OPEN_PROBE_INTERVAL = 2

# Tiered cooldown periods by error type
_CIRCUIT_COOLDOWN_TRANSIENT = 60  # 1 minute for transient errors (timeout, rate limit)
_CIRCUIT_COOLDOWN_PERMANENT = 600  # 10 minutes for permanent errors (model not found, 503)
_CIRCUIT_COOLDOWN_AUTH = 1800  # 30 minutes for auth errors (invalid API key)

_summarize_failures: int = 0
_fallback_calls: int = 0
_circuit_open_time: float | None = None
_circuit_cooldown_seconds: int = _CIRCUIT_COOLDOWN_AUTH

# Anti-consecutive-summarize: after summarization, the local token estimate drops
# drastically but the last AIMessage's usage_metadata.input_tokens still holds the
# pre-summary high value, which would immediately re-trigger summarization.
_skip_next_api_token_check: bool = False


def _get_failures() -> int:
    global _summarize_failures
    return _summarize_failures


def _classify_error_type(exc: Exception) -> str:
    """Classify error type for tiered circuit breaker cooldown.

    Returns:
        Error type: 'auth' | 'permanent' | 'transient'
    """
    exc_str = str(exc).lower()

    if any(
        kw in exc_str
        for kw in [
            "unauthorized",
            "forbidden",
            "invalid api key",
            "authentication failed",
        ]
    ):
        return "auth"

    if any(
        kw in exc_str
        for kw in [
            "model not found",
            "does not exist",
            "not available",
            "no available channel",
        ]
    ):
        return "permanent"

    status_code = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    if status_code in (404, 503):
        return "permanent"

    return "transient"


def _set_failures(n: int, error_type: str = "auth") -> None:
    """Set failure count and cooldown time based on error type."""
    global _summarize_failures, _circuit_open_time, _circuit_cooldown_seconds
    _summarize_failures = n

    if n >= MAX_CONSECUTIVE_SUMMARIZE_FAILURES:
        _circuit_open_time = time.time()

        if error_type == "auth":
            _circuit_cooldown_seconds = _CIRCUIT_COOLDOWN_AUTH
        elif error_type == "permanent":
            _circuit_cooldown_seconds = _CIRCUIT_COOLDOWN_PERMANENT
        else:  # transient
            _circuit_cooldown_seconds = _CIRCUIT_COOLDOWN_TRANSIENT

        logger.warning(
            "[Summarize] Circuit breaker opened, cooldown: %ds (type: %s)",
            _circuit_cooldown_seconds,
            error_type,
        )


def _record_fallback_call() -> None:
    global _fallback_calls
    _fallback_calls += 1


def _is_circuit_open() -> bool:
    """Check if circuit breaker is open (considering cooldown period)."""
    global _summarize_failures, _circuit_open_time, _fallback_calls, _circuit_cooldown_seconds
    failures = _get_failures()
    if failures < MAX_CONSECUTIVE_SUMMARIZE_FAILURES:
        return False

    open_time = _circuit_open_time
    if open_time is None:
        _circuit_open_time = time.time()
        return True

    elapsed = time.time() - open_time
    if elapsed > _circuit_cooldown_seconds:
        logger.info(
            "[Summarize] Circuit breaker cooldown completed (%ds) — attempting auto-recovery",
            _circuit_cooldown_seconds,
        )
        _set_failures(0)
        _fallback_calls = 0
        _circuit_open_time = None
        circuit_breaker_state.labels(component="summarize").set(0)  # CLOSED
        return False

    return True


def _is_half_open_probe() -> bool:
    """Allow one LLM attempt every N fallback calls to detect recovery."""
    global _fallback_calls
    calls = _fallback_calls
    return calls > 0 and calls % _HALF_OPEN_PROBE_INTERVAL == 0


class SummarizeProcessor(BaseProcessor):
    """Summarize processor.

    When context exceeds threshold:
    1. Attempt LLM-generated structured summary (goal, actions, findings, files)
    2. Degrade to deterministic fallback when LLM unavailable (never fails)
    3. Replace old messages with summary + N most recent tool calls
    4. Write StructuredSummary to context.structured_summary (for persistence)

    Three-tier guarantee:
    - L1: LLM summary + output hard-truncation (summarizer.py)
    - L2: Deterministic fallback (this file)
    - L3: Emergency conversation truncation (stream_executor.py)
    """

    def __init__(self, config: ContextConfig | None = None):
        from myrm_agent_harness.agent.context_management.infra.schemas import (
            DEFAULT_CONTEXT_CONFIG,
        )

        self.config = config or DEFAULT_CONTEXT_CONFIG

    @property
    def name(self) -> str:
        return "summarize"

    _HOT_CACHE_WINDOW_SECONDS: float = 300.0  # 5 minutes

    def _should_bypass_for_hot_cache(self, context: ProcessorContext, current_tokens: int) -> bool:
        """Check whether to bypass summarization due to hot cache."""
        max_tokens = self.config.max_context_tokens or 128000
        if current_tokens >= max_tokens * 0.90:
            return False  # MUST summarize synchronously to avoid OOM

        last_active = context.metadata.get("last_activity_time")
        return bool(
            isinstance(last_active, (int, float)) and time.time() - last_active < self._HOT_CACHE_WINDOW_SECONDS
        )

    async def should_process(self, context: ProcessorContext) -> bool:
        global _skip_next_api_token_check
        if context.structured_summary is not None:
            return False

        if context.metadata.get("force_proactive_reset"):
            logger.info("Explicit boundary reset: subtask ended, triggering proactive context compaction")
            return True

        ignore_api = _skip_next_api_token_check
        if _skip_next_api_token_check:
            _skip_next_api_token_check = False

        should_sum = should_summarize(context.messages, config=self.config, ignore_api_tokens=ignore_api)
        if not should_sum:
            return False

        total_tokens = estimate_messages_tokens(context.messages)
        if self._should_bypass_for_hot_cache(context, total_tokens):
            logger.info(
                "[Summarize] Hot cache bypass (tokens=%d), marking compaction_debt_pending",
                total_tokens,
            )
            context.metadata["compaction_debt_pending"] = True
            from ...tracking.task_metrics import get_task_metrics

            if context.chat_id:
                metrics = get_task_metrics(context.chat_id)
                if metrics:
                    metrics.compaction_debt_pending = True
            return False

        logger.info(
            "[Summarize] Cold cache or hard limit reached (tokens=%d), starting summarization",
            total_tokens,
        )
        return True

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        # Prompt Cache preservation: Skip summarize during Resume or HITL session
        if self._should_skip_for_cache_preservation(context):
            logger.info(
                "[Summarize] Skipped for Prompt Cache preservation (is_resume=%s, hitl_session_active=%s)",
                context.is_resume,
                context.merged_context.get("hitl_session_active"),
            )
            return context

        original_tokens = estimate_messages_tokens(context.messages)
        last_msg_db_id = context.metadata.get("last_message_db_id")
        circuit_open = _is_circuit_open()

        summarize_llm = context.summarizer_llm or context.llm
        if summarize_llm is None or (circuit_open and not _is_half_open_probe()):
            reason = "circuit breaker tripped" if circuit_open else "no LLM client"
            logger.warning("[Summarize] %s — using deterministic fallback", reason)
            _record_fallback_call()
            return self._apply_deterministic_fallback(context, original_tokens, last_msg_db_id)

        if circuit_open:
            logger.info("[Summarize] half-open probe — attempting LLM recovery")

        focus_topic = _extract_focus_topic(context.metadata)

        from ...strategies.pre_compact_context import get_pre_compact_message

        pre_compact_message = get_pre_compact_message(context)

        try:
            context.messages, summary = await generate_structured_summary(
                messages=context.messages,
                llm=summarize_llm,
                chat_id=context.chat_id,
                config=self.config,
                focus_topic=focus_topic,
                pre_compact_message=pre_compact_message,
            )
        except Exception as exc:
            from myrm_agent_harness.observability.auth_detector import (
                detect_auth_failure,
                get_auth_error_hint,
            )

            prev = _get_failures()

            error_type_classified = _classify_error_type(exc)

            if detect_auth_failure(exc):
                _set_failures(MAX_CONSECUTIVE_SUMMARIZE_FAILURES, "auth")
                _record_fallback_call()
                auth_hint = get_auth_error_hint(exc)
                logger.error(
                    "[Summarize] Auth failure — circuit breaker opened (30min cooldown) | %s: %s | Hint: %s",
                    type(exc).__name__,
                    exc,
                    auth_hint,
                )
                circuit_breaker_failures_total.labels(component="summarize", error_type="auth").inc()
                circuit_breaker_state.labels(component="summarize").set(2)  # OPEN
                return self._apply_deterministic_fallback(context, original_tokens, last_msg_db_id)

            _set_failures(prev + 1, error_type_classified)
            _record_fallback_call()

            metrics_error_type = (
                error_type_classified
                if error_type_classified != "transient"
                else ("timeout" if "timeout" in str(exc).lower() else "other")
            )
            circuit_breaker_failures_total.labels(component="summarize", error_type=metrics_error_type).inc()

            if prev + 1 >= MAX_CONSECUTIVE_SUMMARIZE_FAILURES:
                circuit_breaker_state.labels(component="summarize").set(2)  # OPEN

            logger.warning(
                "[Summarize] LLM failed (%d/%d) [type: %s, cooldown: %ds] | %s: %s — using deterministic fallback",
                prev + 1,
                MAX_CONSECUTIVE_SUMMARIZE_FAILURES,
                error_type_classified,
                _circuit_cooldown_seconds,
                type(exc).__name__,
                exc,
            )
            return self._apply_deterministic_fallback(context, original_tokens, last_msg_db_id)

        _set_failures(0)
        global _fallback_calls, _skip_next_api_token_check
        _fallback_calls = 0
        _skip_next_api_token_check = True
        circuit_breaker_state.labels(component="summarize").set(0)  # CLOSED (recovered)

        new_tokens = estimate_messages_tokens(context.messages)
        saved = original_tokens - new_tokens
        context.tokens_saved += saved

        context.structured_summary = summary
        if isinstance(last_msg_db_id, str) and last_msg_db_id:
            context.last_summarized_message_id = last_msg_db_id

        from ...infra.cache_break_detector import get_cache_break_detector

        detector = get_cache_break_detector()
        if detector is not None:
            detector.notify_compaction()

        logger.info(
            "[Summarize] done | goal: %s... | saved: %d tokens",
            summary.user_goal[:50],
            saved,
        )

        return context

    def _apply_deterministic_fallback(
        self, context: ProcessorContext, original_tokens: int, last_msg_db_id: object
    ) -> ProcessorContext:
        """Deterministic fallback: build a minimal summary without LLM."""
        summary = _build_deterministic_summary(context.messages, context.metadata, context.chat_id)

        from ...strategies.pre_compact_context import prepend_pre_compact_message
        from ...strategies.summary_builder import extract_protected_head

        protected_head = extract_protected_head(context.messages)

        tail_budget = int((self.config.max_context_tokens or 128000) * getattr(self.config, "tail_budget_ratio", 0.20))
        recent_messages = extract_recent_messages(context.messages, tail_budget)
        summary_message = create_summary_message(summary, context.chat_id)

        context.messages = prepend_pre_compact_message(
            protected_head,
            [summary_message],
            recent_messages,
            context=context,
        )

        new_tokens = estimate_messages_tokens(context.messages)
        saved = original_tokens - new_tokens
        context.tokens_saved += saved

        context.structured_summary = summary
        context.metadata["summarize_fallback_used"] = True
        if isinstance(last_msg_db_id, str) and last_msg_db_id:
            context.last_summarized_message_id = last_msg_db_id

        from ...infra.cache_break_detector import get_cache_break_detector

        detector = get_cache_break_detector()
        if detector is not None:
            detector.notify_compaction()

        global _skip_next_api_token_check
        _skip_next_api_token_check = True

        logger.info(
            "[Summarize] deterministic fallback applied | goal: %s... | saved: %d tokens",
            summary.user_goal[:50],
            saved,
        )
        return context


# ---------------------------------------------------------------------------
# Deterministic summary builder
# ---------------------------------------------------------------------------

_COMPACTED_PATTERN = re.compile(r"COMPACTED: (\w+)\((.+?)\)")
_FALLBACK_GOAL_MAX_CHARS = 300
_FALLBACK_ACTION_MAX_CHARS = 120


def _build_deterministic_summary(
    messages: list[BaseMessage], metadata: dict[str, object], chat_id: str | None = None
) -> StructuredSummary:
    """Extract key information from messages without LLM.

    Extracts:
    - user_goal from the last HumanMessage
    - last_action from the last AIMessage content
    - completed_actions from COMPACTED: patterns in compressed tool results
    - files_modified from ArtifactTracker
    - context_dump_path from metadata snapshot path
    """
    user_goal = "[Unable to extract goal]"
    active_task = ""
    last_action = ""
    completed_actions: list[str] = []
    files_modified: list[str] = []

    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if not active_task:
                active_task = content[:_FALLBACK_GOAL_MAX_CHARS]
                if len(content) > _FALLBACK_GOAL_MAX_CHARS:
                    active_task += "…"
            if user_goal == "[Unable to extract goal]":
                user_goal = content[:_FALLBACK_GOAL_MAX_CHARS]
                if len(content) > _FALLBACK_GOAL_MAX_CHARS:
                    user_goal += "…"

        if isinstance(msg, AIMessage) and not last_action:
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            last_action = content[:_FALLBACK_ACTION_MAX_CHARS]
            if len(content) > _FALLBACK_ACTION_MAX_CHARS:
                last_action += "…"

        if user_goal != "[Unable to extract goal]" and last_action:
            break

    for msg in messages:
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        for match in _COMPACTED_PATTERN.finditer(content):
            tool_name, identifier = match.group(1), match.group(2)
            action = f"{tool_name}: {identifier}"
            if action not in completed_actions:
                completed_actions.append(action)

    try:
        from ...tracking.artifact_tracker import get_artifact_tracker

        if chat_id:
            tracker = get_artifact_tracker(chat_id)
            if tracker:
                all_files = set(tracker.created_files) | set(tracker.modified_files)
                files_modified = sorted(all_files)
    except Exception:
        pass

    context_dump_path = ""
    snapshot_path = metadata.get("context_snapshot_path")
    if isinstance(snapshot_path, str) and snapshot_path:
        context_dump_path = snapshot_path

    return StructuredSummary(
        user_goal=f"[Deterministic fallback — verify via files/commands] {user_goal}",
        completed_actions=completed_actions[:10],
        key_findings=[],
        errors_and_fixes=[],
        files_modified=files_modified[:20],
        last_action=last_action,
        context_dump_path=context_dump_path,
        active_task=active_task,
    )


def _extract_focus_topic(metadata: dict[str, object]) -> str:
    """Extract CompressionIntent.user_goal_hint from metadata as focus topic."""
    intent_data = metadata.get("compression_intent")
    if isinstance(intent_data, dict):
        hint = intent_data.get("user_goal_hint", "")
        if isinstance(hint, str):
            return hint.strip()
    return ""
