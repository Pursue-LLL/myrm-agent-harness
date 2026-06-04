"""Context summarizer.

[INPUT]
- schemas::StructuredSummary (POS: structured summary dataclass with Handoff fields)
- summary_prompts::SUMMARY_PROMPT_TEMPLATE, SUMMARY_MERGE_PROMPT_TEMPLATE, FOCUS_TOPIC_SUFFIX (POS: summary prompt templates)
- summary_parser (POS: summary parsing utilities)
- summary_builder (POS: summary message reconstruction)
- security.detection.leak_detector::redact_leaks (POS: credential leak redaction, output-side + history-side defense)
- toolkits.llms.utils.model_utils::get_model_context_limit (POS: best-effort model context window extraction)
- langchain_core.messages::BaseMessage (POS: LangChain message base class)
- langchain_core.language_models::BaseChatModel (POS: LangChain LLM base class)

[OUTPUT]
- should_summarize: dual-signal check (local estimate OR API input_tokens)
- generate_structured_summary: core summarization function with cache-safe message-prefix invocation (supports focus_topic)

[POS]
Context summarizer. Pure in-memory summarization strategy using structured summary schema (StructuredSummary + Handoff fields), cache-safe message-prefix invocation, and aux-model context guard (_guard_aux_context: auto-trims messages when summarizer LLM has a smaller context window, preventing context_length_exceeded hard failures).

"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field

from myrm_agent_harness.agent.security.detection.leak_detector import redact_leaks
from myrm_agent_harness.toolkits.llms.utils.model_utils import get_model_context_limit
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.token_estimation import estimate_messages_tokens

from ..infra.schemas import ContextConfig, StructuredSummary
from .summary_builder import create_summary_message, extract_recent_messages
from .summary_parser import (
    extract_existing_summary,
    extract_messages_after_summary,
)
from .summary_prompts import (
    FOCUS_TOPIC_SUFFIX,
    SUMMARY_MERGE_PROMPT_TEMPLATE,
    SUMMARY_PROMPT_TEMPLATE,
)


class _FallbackSummaryModel(BaseModel):
    user_goal: str = Field(default="")
    completed_actions: list[str] = Field(default_factory=list)
    key_findings: list[str] = Field(default_factory=list)
    errors_and_fixes: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    last_action: str = Field(default="")
    context_dump_path: str = Field(default="")
    active_task: str = Field(default="")
    constraints_and_preferences: list[str] = Field(default_factory=list)
    resolved_questions: list[str] = Field(default_factory=list)
    pending_user_asks: list[str] = Field(default_factory=list)
    active_state: str = Field(default="")

    def to_structured_summary(self) -> StructuredSummary:
        return StructuredSummary(
            user_goal=self.user_goal,
            completed_actions=self.completed_actions,
            key_findings=self.key_findings,
            errors_and_fixes=self.errors_and_fixes,
            files_modified=self.files_modified,
            last_action=self.last_action,
            context_dump_path=self.context_dump_path,
            active_task=self.active_task,
            constraints_and_preferences=self.constraints_and_preferences,
            resolved_questions=self.resolved_questions,
            pending_user_asks=self.pending_user_asks,
            active_state=self.active_state,
        )


def _get_structured_llm_or_parser(
    llm: BaseChatModel,
) -> tuple[object | None, PydanticOutputParser | None]:
    try:
        structured_llm = llm.with_structured_output(StructuredSummary)
        return structured_llm, None
    except NotImplementedError:
        logger.warning(
            " Model does not support with_structured_output natively, degrading to PydanticOutputParser"
        )
        return None, PydanticOutputParser(pydantic_object=_FallbackSummaryModel)


_REDACT_SKIP_FIELDS = frozenset({"context_dump_path", "files_modified"})


def _redact_summary_fields(summary: StructuredSummary) -> StructuredSummary:
    """Apply credential redaction to all text fields of a StructuredSummary.

    Skips context_dump_path (filesystem path) and files_modified (filenames)
    which cannot contain credentials. Safe no-op when nothing matches.
    """
    for field_name in summary.__dataclass_fields__:
        if field_name in _REDACT_SKIP_FIELDS:
            continue
        value = getattr(summary, field_name)
        if isinstance(value, str) and value:
            setattr(summary, field_name, redact_leaks(value))
        elif isinstance(value, list):
            setattr(
                summary,
                field_name,
                [
                    redact_leaks(item) if isinstance(item, str) else item
                    for item in value
                ],
            )
    return summary


async def _invoke_summary(
    llm: BaseChatModel,
    structured_llm: object | None,
    parser: PydanticOutputParser | None,
    prompt: str,
    dump_path: str,
    cache_prefix_messages: list[BaseMessage] | None = None,
) -> StructuredSummary:
    if parser:
        instructions = parser.get_format_instructions()
        final_prompt = f"{prompt}\n\n{instructions}"
        response = await llm.ainvoke(
            _build_summary_invocation_messages(final_prompt, cache_prefix_messages)
        )
        parsed = parser.invoke(response)
        summary = parsed.to_structured_summary()
    else:
        summary = await structured_llm.ainvoke(  # type: ignore
            _build_summary_invocation_messages(prompt, cache_prefix_messages)
        )

    summary.context_dump_path = dump_path
    summary = _redact_summary_fields(summary)
    return summary


def _build_summary_invocation_messages(
    prompt: str,
    cache_prefix_messages: list[BaseMessage] | None,
) -> list[BaseMessage]:
    if not cache_prefix_messages:
        return [HumanMessage(content=prompt)]
    return [*cache_prefix_messages, HumanMessage(content=prompt)]


logger = get_agent_logger(__name__)

_AUX_CONTEXT_SAFETY_RATIO = 0.8
_AUX_PROMPT_OVERHEAD = 2000


def _guard_aux_context(
    messages: list[BaseMessage],
    llm: BaseChatModel,
    prompt_tokens: int = _AUX_PROMPT_OVERHEAD,
) -> list[BaseMessage]:
    """Trim messages to fit within the aux model's context window.

    When the summarizer LLM has a smaller context window than the main model,
    the full message history may exceed its capacity, causing a hard
    ``context_length_exceeded`` error. This guard trims from the head (keeping
    the most recent messages) so the LLM call stays within safe bounds.

    Returns the original list unchanged when no trimming is needed or when the
    model's context limit cannot be determined (graceful no-op).
    """
    aux_limit = get_model_context_limit(llm)
    if aux_limit is None:
        return messages

    safe_budget = int(aux_limit * _AUX_CONTEXT_SAFETY_RATIO) - prompt_tokens
    if safe_budget <= 0:
        logger.warning(
            "[Summarize] Aux model context too small to hold even the prompt "
            "(limit=%d, prompt_overhead=%d) — skipping guard",
            aux_limit, prompt_tokens,
        )
        return messages

    total_tokens = estimate_messages_tokens(messages)
    if total_tokens <= safe_budget:
        return messages

    trimmed: list[BaseMessage] = []
    running = 0
    for msg in reversed(messages):
        msg_tokens = estimate_messages_tokens([msg])
        if running + msg_tokens > safe_budget:
            break
        trimmed.insert(0, msg)
        running += msg_tokens

    if not trimmed:
        trimmed = messages[-1:]

    logger.warning(
        "[Summarize] Aux context guard: trimmed %d → %d messages "
        "(aux_limit=%d, safe_budget=%d, original_tokens=%d)",
        len(messages), len(trimmed), aux_limit, safe_budget, total_tokens,
    )
    return trimmed


def should_summarize(
    messages: list[BaseMessage],
    config: ContextConfig | None = None,
    ignore_api_tokens: bool = False,
) -> bool:
    """Check whether proactive summarization should be triggered (dual-signal)."""
    from ..infra.schemas import DEFAULT_CONTEXT_CONFIG

    cfg = config or DEFAULT_CONTEXT_CONFIG
    total_tokens = estimate_messages_tokens(messages)
    max_window = cfg.max_context_tokens or 120000
    threshold = cfg.proactive_reset_threshold

    if total_tokens >= threshold:
        ratio = total_tokens / max_window
        logger.warning(
            f" [Summarize] proactive_reset triggered: "
            f"tokens={total_tokens}, threshold={threshold}, "
            f"max_window={max_window}, ratio={ratio:.1%}"
        )
        return True

    passive_threshold = cfg.summarize_trigger_threshold
    if total_tokens >= passive_threshold:
        ratio = total_tokens / max_window
        logger.warning(
            f" [Summarize] passive threshold triggered: "
            f"tokens={total_tokens}, threshold={passive_threshold}, "
            f"max_window={max_window}, ratio={ratio:.1%}"
        )
        return True

    if ignore_api_tokens:
        return False

    api_input_tokens = 0
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            usage = getattr(msg, "usage_metadata", None)
            if usage and isinstance(usage, dict):
                api_input_tokens = usage.get("input_tokens", 0)

            if api_input_tokens == 0:
                resp_meta = getattr(msg, "response_metadata", {})
                if isinstance(resp_meta, dict):
                    token_usage = resp_meta.get("token_usage", {})
                    if isinstance(token_usage, dict):
                        api_input_tokens = token_usage.get("prompt_tokens", 0)

            break

    if api_input_tokens >= threshold:
        ratio = api_input_tokens / max_window
        logger.warning(
            f" [Summarize] API token signal triggered: "
            f"local_estimate={total_tokens}, api_input={api_input_tokens}, "
            f"threshold={threshold}, max_window={max_window}, ratio={ratio:.1%}"
        )
        return True

    logger.debug(
        f" [Summarize Check] total={total_tokens}, api_input={api_input_tokens}, "
        f"threshold={threshold}, max_window={max_window}"
    )
    return False


async def generate_structured_summary(
    messages: list[BaseMessage],
    llm: BaseChatModel,
    chat_id: str | None = None,
    existing_summary: StructuredSummary | None = None,
    config: ContextConfig | None = None,
    focus_topic: str = "",
    pre_compact_message: BaseMessage | None = None,
) -> tuple[list[BaseMessage], StructuredSummary]:
    """Generate structured summary and rebuild message list (pure in-memory).

    Two modes:
    1. Full: generate a complete new summary
    2. Incremental: merge new content into an existing summary
    """
    from ..infra.schemas import DEFAULT_CONTEXT_CONFIG

    cfg = config or DEFAULT_CONTEXT_CONFIG

    if existing_summary is None:
        existing_summary = extract_existing_summary(messages)

    is_incremental = existing_summary is not None
    mode_str = "incremental" if is_incremental else "full"
    logger.warning(" Starting context summary (%s)...", mode_str)

    dump_path = ""

    from .summary_auditor import extract_key_entities

    entities = extract_key_entities(messages)

    if is_incremental and existing_summary is not None:
        new_messages_only = extract_messages_after_summary(messages)
        if new_messages_only:
            summary = await _summarize_incremental_with_audit(
                llm,
                existing_summary,
                new_messages_only,
                dump_path,
                messages,
                entities,
                focus_topic=focus_topic,
            )
        else:
            summary = existing_summary
            summary.context_dump_path = dump_path
            logger.warning(" No new content, keeping existing summary")
    else:
        summary = await _summarize_full_with_audit(
            llm, messages, dump_path, entities, focus_topic=focus_topic
        )

    tail_budget = int((cfg.max_context_tokens or 128000) * getattr(cfg, "tail_budget_ratio", 0.20))
    recent_messages = extract_recent_messages(messages, tail_budget)
    original_tokens = estimate_messages_tokens(messages)

    summary = _cap_summary_if_needed(summary, original_tokens, recent_messages, chat_id)

    import hashlib
    import re

    from .summary_builder import extract_protected_head

    protected_head = extract_protected_head(messages)

    # Remove old preserved context messages to prevent accumulation
    protected_head = [
        msg for msg in protected_head
        if not (isinstance(msg, SystemMessage) and str(msg.content).startswith("[SYSTEM: PRESERVED CONTEXT]"))
    ]

    # --- Generic Context Preservation Logic ---
    # Extracts <preserve_context> tags from any message, deduplicates them,
    # truncates them to prevent OOM, and injects them into the protected_head
    # to maximize Prompt Cache hits.
    rescued_context_blocks = {}
    preserve_tag_pattern = re.compile(r"<preserve_context>(.*?)</preserve_context>", re.DOTALL | re.IGNORECASE)
    max_preserve_chars = 2000

    for msg in messages:
        content_str = str(msg.content)
        matches = preserve_tag_pattern.findall(content_str)
        for match in matches:
            clean_match = match.strip()
            if not clean_match:
                continue

            if len(clean_match) > max_preserve_chars:
                clean_match = clean_match[:max_preserve_chars] + "\n...[TRUNCATED]"

            block_hash = hashlib.md5(clean_match.encode('utf-8')).hexdigest()
            if block_hash not in rescued_context_blocks:
                # Re-wrap in tags so it survives multiple summarizations
                rescued_context_blocks[block_hash] = f"<preserve_context>\n{clean_match}\n</preserve_context>"

    if rescued_context_blocks:
        combined_preserved = "\n\n".join(rescued_context_blocks.values())
        # Inject directly into protected_head (Prefix) to maximize cache hits
        protected_head.append(
            SystemMessage(content=f"[SYSTEM: PRESERVED CONTEXT]\nThe following critical context was preserved from history:\n{combined_preserved}")
        )
    # --------------------------

    summary_message = create_summary_message(summary, chat_id)
    middle_messages = [summary_message]
    if pre_compact_message is not None:
        middle_messages = [pre_compact_message, summary_message]

    new_messages = protected_head + middle_messages + recent_messages

    new_tokens = estimate_messages_tokens(new_messages)
    saved_tokens = original_tokens - new_tokens

    logger.warning(
        " Summary done: %d -> %d tokens (saved %d)", original_tokens, new_tokens, saved_tokens
    )

    mode_detail = "incremental" if is_incremental else "full"
    _record_summarize_to_metrics(
        saved_tokens, f"Summarized {len(messages)} messages ({mode_detail})"
    )

    return new_messages, summary


# ---------------------------------------------------------------------------
# Summary budget calculation
# ---------------------------------------------------------------------------

_SUMMARY_RATIO = 0.20
_MIN_SUMMARY_TOKENS = 2000
_MAX_SUMMARY_TOKENS = 12000


def _build_budget_hint(content_tokens: int) -> str:
    """Build a budget hint for the summary prompt.

    Allocates 20% of compressed content as budget, clamped to [2000, 12000] tokens.
    """
    budget = max(
        _MIN_SUMMARY_TOKENS,
        min(int(content_tokens * _SUMMARY_RATIO), _MAX_SUMMARY_TOKENS),
    )
    return (
        f"\nTarget length: ~{budget} tokens. Be specific and concise — "
        f"include file paths, command outputs, error messages, and exact values. "
        f"Avoid vague descriptions."
    )


# ---------------------------------------------------------------------------
# Summary output capping (prevent summary bloat)
# ---------------------------------------------------------------------------

_CAP_MAX_ACTIONS = 5
_CAP_MAX_FINDINGS = 3
_CAP_MAX_ERRORS = 3
_CAP_GOAL_MAX_CHARS = 200


def _cap_summary_if_needed(
    summary: StructuredSummary,
    original_tokens: int,
    recent_messages: list[BaseMessage],
    chat_id: str | None,
) -> StructuredSummary:
    """Ensure summarised output is shorter than the original.

    Applies progressive truncation following the Lost-in-Middle principle:
    truncate middle fields first (completed_actions), preserve start
    (user_goal) and end (errors_and_fixes).
    """
    summary_message = create_summary_message(summary, chat_id)
    new_tokens = estimate_messages_tokens([summary_message, *recent_messages])

    if new_tokens < original_tokens:
        return summary

    logger.warning(
        " Summary bloat detected: %d → %d tokens, applying progressive cap",
        original_tokens,
        new_tokens,
    )

    # Phase 1: trim middle-attention fields first
    summary.completed_actions = summary.completed_actions[:_CAP_MAX_ACTIONS]
    summary.key_findings = summary.key_findings[:_CAP_MAX_FINDINGS]
    summary.errors_and_fixes = summary.errors_and_fixes[:_CAP_MAX_ERRORS]
    summary.resolved_questions = summary.resolved_questions[:3]

    summary_message = create_summary_message(summary, chat_id)
    new_tokens = estimate_messages_tokens([summary_message, *recent_messages])
    if new_tokens < original_tokens:
        return summary

    # Phase 2: aggressive trimming
    if len(summary.user_goal) > _CAP_GOAL_MAX_CHARS:
        summary.user_goal = summary.user_goal[:_CAP_GOAL_MAX_CHARS] + "…"
    summary.completed_actions = summary.completed_actions[:2]
    summary.key_findings = summary.key_findings[:1]
    summary.resolved_questions = summary.resolved_questions[:1]
    summary.constraints_and_preferences = summary.constraints_and_preferences[:2]

    logger.warning(" Applied aggressive cap to summary fields")
    return summary


# ---------------------------------------------------------------------------
# Audit + retry orchestration
# ---------------------------------------------------------------------------

_MAX_AUDIT_RETRIES = 2


async def _summarize_full_with_audit(
    llm: BaseChatModel,
    messages: list[BaseMessage],
    dump_path: str,
    entities: set[str],
    focus_topic: str = "",
) -> StructuredSummary:
    """Generate a full summary with quality audit and retry."""
    from .summary_auditor import audit_summary, build_retry_guidance

    original_tokens = estimate_messages_tokens(messages)
    budget_hint = _build_budget_hint(original_tokens)

    cache_safe_base_prompt = SUMMARY_PROMPT_TEMPLATE.format(
        context="Use the preceding conversation messages as the Conversation History.",
        budget_hint=budget_hint,
    )
    if focus_topic:
        cache_safe_base_prompt += FOCUS_TOPIC_SUFFIX.format(focus_topic=focus_topic)

    best: StructuredSummary | None = None
    best_retained = -1

    structured_llm, parser = _get_structured_llm_or_parser(llm)

    prompt_tokens = estimate_messages_tokens(
        [HumanMessage(content=cache_safe_base_prompt)]
    )
    guarded_messages = _guard_aux_context(messages, llm, prompt_tokens)

    for attempt in range(_MAX_AUDIT_RETRIES + 1):
        prompt = cache_safe_base_prompt
        if attempt > 0 and best is not None:
            guidance = build_retry_guidance(
                audit_summary(best, messages, entities=entities)
            )
            prompt = f"{cache_safe_base_prompt}\n\n Quality feedback:\n{guidance}"

        try:
            summary = await _invoke_summary(
                llm,
                structured_llm,
                parser,
                prompt,
                dump_path,
                cache_prefix_messages=guarded_messages,
            )
        except Exception as e:
            logger.warning(" Structured output failed: %s", e)
            if attempt == _MAX_AUDIT_RETRIES and best is None:
                raise ValueError(f"Failed to generate structured summary: {e}") from e
            continue

        result = audit_summary(summary, messages, entities=entities)
        if result.entity_retained > best_retained:
            best = summary
            best_retained = result.entity_retained

        if result.passed:
            logger.warning(
                " Full summary done (attempt %d): goal=%s...",
                attempt + 1,
                summary.user_goal[:50],
            )
            return summary

        logger.warning(
            " Summary audit failed (attempt %d/%d): %s",
            attempt + 1,
            _MAX_AUDIT_RETRIES + 1,
            "; ".join(result.issues),
        )

    logger.warning(
        " Using best summary after %d attempts (retained %d entities)",
        _MAX_AUDIT_RETRIES + 1,
        best_retained,
    )
    return best  # type: ignore[return-value]


async def _summarize_incremental_with_audit(
    llm: BaseChatModel,
    existing_summary: StructuredSummary,
    new_messages: list[BaseMessage],
    dump_path: str,
    all_messages: list[BaseMessage],
    entities: set[str],
    focus_topic: str = "",
) -> StructuredSummary:
    """Generate an incremental summary with quality audit and retry."""
    from .summary_auditor import audit_summary, build_retry_guidance

    existing_summary = _redact_summary_fields(existing_summary)

    new_tokens = estimate_messages_tokens(new_messages)
    budget_hint = _build_budget_hint(new_tokens)

    cache_safe_base_prompt = SUMMARY_MERGE_PROMPT_TEMPLATE.format(
        existing_summary=existing_summary.to_json(),
        new_context="Use the preceding conversation messages as the New Conversation Content.",
        budget_hint=budget_hint,
    )
    if focus_topic:
        cache_safe_base_prompt += FOCUS_TOPIC_SUFFIX.format(focus_topic=focus_topic)

    best: StructuredSummary | None = None
    best_retained = -1

    structured_llm, parser = _get_structured_llm_or_parser(llm)

    prompt_tokens = estimate_messages_tokens(
        [HumanMessage(content=cache_safe_base_prompt)]
    )
    guarded_new_messages = _guard_aux_context(new_messages, llm, prompt_tokens)

    for attempt in range(_MAX_AUDIT_RETRIES + 1):
        prompt = cache_safe_base_prompt
        if attempt > 0 and best is not None:
            guidance = build_retry_guidance(
                audit_summary(best, all_messages, entities=entities)
            )
            prompt = f"{cache_safe_base_prompt}\n\n Quality feedback:\n{guidance}"

        try:
            summary = await _invoke_summary(
                llm,
                structured_llm,
                parser,
                prompt,
                dump_path,
                cache_prefix_messages=guarded_new_messages,
            )
        except Exception as e:
            logger.warning(" Structured output failed: %s", e)
            if attempt == _MAX_AUDIT_RETRIES and best is None:
                raise ValueError(f"Failed to generate structured summary: {e}") from e
            continue

        result = audit_summary(summary, all_messages, entities=entities)
        if result.entity_retained > best_retained:
            best = summary
            best_retained = result.entity_retained

        if result.passed:
            _log_merge_quality(existing_summary, summary)
            logger.warning(
                " Incremental merge done (attempt %d): goal=%s...",
                attempt + 1,
                summary.user_goal[:50],
            )
            return summary

        logger.warning(
            " Incremental audit failed (attempt %d/%d): %s",
            attempt + 1,
            _MAX_AUDIT_RETRIES + 1,
            "; ".join(result.issues),
        )

    _log_merge_quality(existing_summary, best)  # type: ignore[arg-type]
    logger.warning(
        " Using best incremental summary after %d attempts (retained %d entities)",
        _MAX_AUDIT_RETRIES + 1,
        best_retained,
    )
    return best  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _log_merge_quality(before: StructuredSummary, after: StructuredSummary) -> None:
    """Record incremental merge quality metrics (pre/post information count)."""
    actions_before = len(before.completed_actions)
    actions_after = len(after.completed_actions)
    findings_before = len(before.key_findings)
    findings_after = len(after.key_findings)
    errors_before = len(before.errors_and_fixes)
    errors_after = len(after.errors_and_fixes)
    files_before = len(before.files_modified)
    files_after = len(after.files_modified)

    changes: list[str] = []
    for label, b, a in [
        ("actions", actions_before, actions_after),
        ("findings", findings_before, findings_after),
        ("errors", errors_before, errors_after),
        ("files", files_before, files_after),
    ]:
        suffix = " " if a < b else ""
        changes.append(f"{label}: {b}→{a}{suffix}")

    has_loss = (
        actions_after < actions_before
        or findings_after < findings_before
        or errors_after < errors_before
        or files_after < files_before
    )

    if has_loss:
        logger.warning(f" Incremental merge may have lost info: {', '.join(changes)}")
    else:
        logger.warning(f" Incremental merge quality: {', '.join(changes)}")


def _record_summarize_to_metrics(tokens_saved: int, details: str = "") -> None:
    """Record a summarize event to TaskMetrics."""
    try:
        from myrm_agent_harness.agent.context_management.infra.session_lock import (
            get_current_chat_id,
        )
        from myrm_agent_harness.agent.context_management.tracking.task_metrics import (
            get_task_metrics,
        )

        chat_id = get_current_chat_id()
        if chat_id:
            metrics = get_task_metrics(chat_id)
            if metrics:
                metrics.record_compression(
                    tokens_saved=tokens_saved,
                    compression_type="summarize",
                    details=details,
                )
    except Exception as e:
        logger.warning("[Summarize] Failed to record to TaskMetrics: %s", e)
